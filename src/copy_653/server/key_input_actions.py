"""Key-input WebSocket actions for the Copy web server.

Owns the server-side MIDI key-input path, the shared push/flush
helpers used by both server-side and browser-side MIDI input, and the
browser key-input session state.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from websockets.server import WebSocketServerProtocol

from copy_653.audio import timing
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    KeyerSettings,
    load_audio_parameters,
    load_keyer_settings,
)
from copy_653.midi import (
    KeyDecoder,
    KeyElementAssembler,
    MidiNoteEvent,
    iter_midi_note_events,
)
from copy_653.server.wire_events import (
    _key_event_event,
    _key_input_start_event,
    _send_event,
    _sent_symbol_event,
)

logger = logging.getLogger(__name__)


KeyNoteSource = Callable[[threading.Event], Iterator[MidiNoteEvent]]


async def _push_key_note_event(
    ws: WebSocketServerProtocol,
    item: MidiNoteEvent,
    *,
    settings: KeyerSettings,
    audio_params: AudioParameters,
    assembler: KeyElementAssembler,
    decoder: KeyDecoder,
    recorder: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    """Apply one note event to the key decoder and emit any resulting events.

    Returns ``True`` if this event completed a key element (a note-off that
    closed an active note-on). Callers use the return value to gate the
    character-gap flush timer so it never fires mid-stroke between a
    note-on and its matching note-off.

    If ``recorder`` is provided, every event payload sent to the client
    is also handed to it. Used by the Cadence session recorder to
    accumulate sent symbols and raw MIDI events.
    """
    element = assembler.push(item, settings)
    key_event = _key_event_event(item, settings, audio_params, element)
    if key_event is not None:
        await _send_event(ws, key_event)
        if recorder is not None:
            recorder(key_event)
    if element is None:
        return False

    try:
        decoded = decoder.push(element)
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "key-input-decode-failed", "detail": str(exc)},
        )
        decoder.reset()
        return True
    if decoded is not None:
        sent_event = _sent_symbol_event(decoded)
        await _send_event(ws, sent_event)
        if recorder is not None:
            recorder(sent_event)
    return True


async def _flush_key_symbol(
    ws: WebSocketServerProtocol,
    decoder: KeyDecoder,
    recorder: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Force a flush of any pending marks; the caller has already waited
    the character gap externally (timer task or wait_for timeout).

    ``recorder`` mirrors :func:`_push_key_note_event`'s contract: when
    provided, the sent-symbol payload is also handed to it so the
    Cadence session record captures timer-flushed symbols (i.e. the
    last symbol a learner keys, or any symbol finalised by silence
    rather than by the next stroke).
    """
    decoded = decoder.flush_pending()
    if decoded is not None:
        sent_event = _sent_symbol_event(decoded)
        await _send_event(ws, sent_event)
        if recorder is not None:
            recorder(sent_event)


async def _run_key_input_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
    note_source: KeyNoteSource | None = None,
    recorder: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Receive Trinkey MIDI note events, decode symbols, and push them to the page."""
    try:
        settings = load_keyer_settings(config_path)
        audio_params = load_audio_parameters(config_path)
    except ValueError as exc:
        await _send_event(ws, {"type": "error", "reason": "invalid-config", "detail": str(exc)})
        return

    decoder = KeyDecoder(
        dit_seconds=timing.dit_seconds(audio_params.character_speed_wpm),
        character_gap_seconds=timing.send_inter_character_seconds(audio_params.character_speed_wpm),
        word_gap_seconds=timing.send_inter_word_seconds(audio_params.character_speed_wpm),
    )
    assembler = KeyElementAssembler()
    source = note_source or (
        lambda stop: iter_midi_note_events(port_name=settings.input_name, stop_event=stop)
    )
    queue: asyncio.Queue[MidiNoteEvent | BaseException | None] = asyncio.Queue()
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    def _queue_from_thread(item: MidiNoteEvent | BaseException | None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:
            pass

    def _read_midi() -> None:
        try:
            for note_event in source(stop_event):
                if stop_event.is_set():
                    break
                _queue_from_thread(note_event)
        except BaseException as exc:
            _queue_from_thread(exc)
        finally:
            _queue_from_thread(None)

    thread = threading.Thread(target=_read_midi, name="copy-653-key-midi", daemon=True)
    thread.start()
    character_gap_seconds = timing.send_inter_character_seconds(audio_params.character_speed_wpm)

    await _send_event(ws, _key_input_start_event(settings, audio_params))

    # Deadline (loop.time) for the next character-gap flush. ``None`` means no
    # element is awaiting flush (we're either idle or mid-stroke between a
    # note-on and its note-off). Rearming this on every event would race the
    # next note-off and split a single character into two symbols.
    flush_deadline: float | None = None

    try:
        while True:
            if flush_deadline is None:
                item = await queue.get()
            else:
                timeout = max(0.0, flush_deadline - loop.time())
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    await _flush_key_symbol(ws, decoder, recorder)
                    flush_deadline = None
                    continue

            if item is None:
                await _flush_key_symbol(ws, decoder, recorder)
                return
            if isinstance(item, BaseException):
                reason = (
                    "key-input-unavailable" if isinstance(item, ImportError) else "key-input-failed"
                )
                await _send_event(ws, {"type": "error", "reason": reason, "detail": str(item)})
                return

            formed_element = await _push_key_note_event(
                ws,
                item,
                settings=settings,
                audio_params=audio_params,
                assembler=assembler,
                decoder=decoder,
                recorder=recorder,
            )
            if formed_element:
                flush_deadline = loop.time() + character_gap_seconds
            else:
                # Note-on: element in progress. Disarm the flush so it can't
                # fire between this note-on and its matching note-off.
                flush_deadline = None
    finally:
        stop_event.set()
        await asyncio.to_thread(thread.join, 1.0)


@dataclass
class BrowserKeyInputState:
    """In-flight state for a browser MIDI key-input session.

    Created on ``start-browser-key-input``, retired on ``stop-key-input``
    or socket close. Owns its own per-character-gap flush task so a
    pending flush is cancelled cleanly when the state retires.
    """

    ws: WebSocketServerProtocol
    settings: KeyerSettings
    audio_params: AudioParameters
    assembler: KeyElementAssembler
    decoder: KeyDecoder
    # Offset from browser performance.now() (seconds) to server
    # time.monotonic() (seconds), captured once per session so element
    # timestamps and timer-driven flushes share one clock domain.
    clock_offset: float | None = None
    flush_task: asyncio.Task[None] | None = None
    # Forwarded to the timer-driven flush so symbols finalised by
    # silence (the common case) reach the Cadence record alongside
    # symbols finalised by the next stroke's gap-in-push.
    recorder: Callable[[dict[str, Any]], None] | None = None

    async def cancel_flush(self) -> None:
        if self.flush_task is not None and not self.flush_task.done():
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        self.flush_task = None

    def schedule_flush(self) -> None:
        if self.flush_task is not None and not self.flush_task.done():
            self.flush_task.cancel()

        async def _flush_after_gap() -> None:
            await asyncio.sleep(
                timing.send_inter_character_seconds(self.audio_params.character_speed_wpm)
            )
            await _flush_key_symbol(self.ws, self.decoder, self.recorder)

        self.flush_task = asyncio.create_task(_flush_after_gap())

    async def reset(self, reason: str) -> None:
        await self.cancel_flush()
        self.assembler = KeyElementAssembler()
        self.decoder.reset()
        await _send_event(self.ws, {"type": "key-input-reset", "reason": reason})

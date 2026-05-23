# Changelog

## [0.10.1](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.10.0...v0.10.1) (2026-05-23)


### Bug Fixes

* **koch:** wire scaffold-break to gear state, not next-symbol evidence ([32248b7](https://github.com/malloc-labs/malloc-labs-copy/commit/32248b7e1a0c9be85e097d69e3abbd2e3f9615da))
* **koch:** wire scaffold-break to gear state, not next-symbol evidence ([7ca83e7](https://github.com/malloc-labs/malloc-labs-copy/commit/7ca83e713fa9c1b1d4ac88260e796c074898aa1d))

## [0.10.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.9.1...v0.10.0) (2026-05-22)


### Features

* **guided:** preview a symbol with Left Alt + key on Symbol Exposure ([#118](https://github.com/malloc-labs/malloc-labs-copy/issues/118)) ([d6315f2](https://github.com/malloc-labs/malloc-labs-copy/commit/d6315f2dd29510502bf593fa946e226b87a28e00))
* **guided:** R keybind and layout polish for symbol-truth disclosure ([#121](https://github.com/malloc-labs/malloc-labs-copy/issues/121)) ([c0b28dc](https://github.com/malloc-labs/malloc-labs-copy/commit/c0b28dc493e379080e3e1ff50d5f73af96702a8d))
* **key:** send-side readiness signal for the next-symbol nudge ([#125](https://github.com/malloc-labs/malloc-labs-copy/issues/125)) ([47ebd51](https://github.com/malloc-labs/malloc-labs-copy/commit/47ebd510d8d1cba48d004703c24af22fd0b0234f))
* **koch:** 60-min per-claimed-set soft gate on the next-symbol nudge ([#131](https://github.com/malloc-labs/malloc-labs-copy/issues/131)) ([3f99a52](https://github.com/malloc-labs/malloc-labs-copy/commit/3f99a52680fc698ac5dad28c08228bf0332f9b44))
* **koch:** gear 3 stage 1 — randomise DE lead-in once evidence is ready ([#134](https://github.com/malloc-labs/malloc-labs-copy/issues/134)) ([5551b60](https://github.com/malloc-labs/malloc-labs-copy/commit/5551b60c5581f285f2c9990605206eee6486eb9a))
* **koch:** gear 3 stage 2 — dynamic noise floor under scaffold-break ([#135](https://github.com/malloc-labs/malloc-labs-copy/issues/135)) ([d16343b](https://github.com/malloc-labs/malloc-labs-copy/commit/d16343b5646b79160154a77921a87b2207999918))
* **koch:** invert gear-down asymmetry — 4 low runs to retreat, RST sub-axis stays at 2 ([#140](https://github.com/malloc-labs/malloc-labs-copy/issues/140)) ([e1e0163](https://github.com/malloc-labs/malloc-labs-copy/commit/e1e01637af24fdbf2ae47ebc1f9b5e7bde186e9e))
* **koch:** RST sub-axis at gear 3 + Settings RST relabel ([#138](https://github.com/malloc-labs/malloc-labs-copy/issues/138)) ([22a2c21](https://github.com/malloc-labs/malloc-labs-copy/commit/22a2c212e63ffd7c1eec8d5877069797f87d371c))
* **koch:** S keybind and 5-second countdown for Start ([#123](https://github.com/malloc-labs/malloc-labs-copy/issues/123)) ([2275ec6](https://github.com/malloc-labs/malloc-labs-copy/commit/2275ec6cad84c4d6df88e58599d9a8c02bc1811e))
* **koch:** split next-symbol signal into evidence-ready + full-gate ([#132](https://github.com/malloc-labs/malloc-labs-copy/issues/132)) ([6e92a8d](https://github.com/malloc-labs/malloc-labs-copy/commit/6e92a8ddc4b3660b1665464c9de74ecae6611152))
* **koch:** two-column Answers/Sent review table with correctness colouring ([#139](https://github.com/malloc-labs/malloc-labs-copy/issues/139)) ([5d3b520](https://github.com/malloc-labs/malloc-labs-copy/commit/5d3b520018fb9d42ca0e0bebf103d2111ac5c866))
* **settings:** Back up button for Koch and Key record directories ([#126](https://github.com/malloc-labs/malloc-labs-copy/issues/126)) ([6000de4](https://github.com/malloc-labs/malloc-labs-copy/commit/6000de45cc8d944dd2e70b52aa4c8b7655085cc2))
* **settings:** per-claimed-set cumulative on practice calendars ([#130](https://github.com/malloc-labs/malloc-labs-copy/issues/130)) ([c66009e](https://github.com/malloc-labs/malloc-labs-copy/commit/c66009e26b0bd66ebc34765c58ef7a8341187388))
* **settings:** per-day practice minutes on the Koch calendar ([#124](https://github.com/malloc-labs/malloc-labs-copy/issues/124)) ([9f6eb36](https://github.com/malloc-labs/malloc-labs-copy/commit/9f6eb368fcaadbfe6b95defd6a0c05da4ec83d42))
* **settings:** practice calendars as popups on Koch and Key tabs ([#127](https://github.com/malloc-labs/malloc-labs-copy/issues/127)) ([7a8691b](https://github.com/malloc-labs/malloc-labs-copy/commit/7a8691b39dc0ab5fdb714b21259f34dfb9e90c80))
* **settings:** surface gear 3 in detail dialog and refresh calendar on open ([#136](https://github.com/malloc-labs/malloc-labs-copy/issues/136)) ([8b6ef2d](https://github.com/malloc-labs/malloc-labs-copy/commit/8b6ef2d1086bd2b4ea8e794cd2a8dce5aa3147de))
* **web:** keyboard accelerators across landing and back-links ([#122](https://github.com/malloc-labs/malloc-labs-copy/issues/122)) ([48f7232](https://github.com/malloc-labs/malloc-labs-copy/commit/48f7232ca46dbe6814333c0285ea9475fc2461fa))


### Bug Fixes

* **audio:** apply receiver bed once per session, not per exercise ([#129](https://github.com/malloc-labs/malloc-labs-copy/issues/129)) ([5c92e81](https://github.com/malloc-labs/malloc-labs-copy/commit/5c92e81c95f3964cb70ff6329d8de32ca36446d5))
* **guided:** drop typographic dit/dah line from symbol truth ([#120](https://github.com/malloc-labs/malloc-labs-copy/issues/120)) ([1aab275](https://github.com/malloc-labs/malloc-labs-copy/commit/1aab2758b42ea050a972bfc11ea41b1a49716cc9))
* **koch:** split CSS so the in-contention box renders without colour ([#133](https://github.com/malloc-labs/malloc-labs-copy/issues/133)) ([84be93b](https://github.com/malloc-labs/malloc-labs-copy/commit/84be93b05ca92e705d0858e45ab582296c8609a8))
* **settings:** delete buttons request GET, not POST ([#128](https://github.com/malloc-labs/malloc-labs-copy/issues/128)) ([92982a7](https://github.com/malloc-labs/malloc-labs-copy/commit/92982a7743f8a78587d04cfb029454f182d944b3))

## [0.9.1](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.9.0...v0.9.1) (2026-05-20)


### Bug Fixes

* **docs:** refresh README status, surfaces, and Settings tabs ([#115](https://github.com/malloc-labs/malloc-labs-copy/issues/115)) ([0316d8c](https://github.com/malloc-labs/malloc-labs-copy/commit/0316d8c8284e0f0ac6a9d38d23e443a8bb8f3517))
* **settings:** restore last-row bottom border on lifetime history grid ([#117](https://github.com/malloc-labs/malloc-labs-copy/issues/117)) ([fc7ad0f](https://github.com/malloc-labs/malloc-labs-copy/commit/fc7ad0f461ef748124f8955400f329086c445433))

## [0.9.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.8.0...v0.9.0) (2026-05-20)


### Features

* **key:** show keyer mode badge in cadence/freeplay header ([#111](https://github.com/malloc-labs/malloc-labs-copy/issues/111)) ([f883c23](https://github.com/malloc-labs/malloc-labs-copy/commit/f883c23ea7c9e236dadb1568ff74060e56285dae))
* **koch:** adaptive per-band gears and lifetime diagnostics ([#97](https://github.com/malloc-labs/malloc-labs-copy/issues/97)) ([7c9f252](https://github.com/malloc-labs/malloc-labs-copy/commit/7c9f252de4fe558e2d2f46c8246c6a61c06495f5))
* **koch:** readiness signal for the next-symbol nudge ([#109](https://github.com/malloc-labs/malloc-labs-copy/issues/109)) ([09f8783](https://github.com/malloc-labs/malloc-labs-copy/commit/09f8783589fdab1acae325790d599309637d1fd2))
* **settings:** add Calendar tab for per-day practice monitoring ([#110](https://github.com/malloc-labs/malloc-labs-copy/issues/110)) ([eeb2f21](https://github.com/malloc-labs/malloc-labs-copy/commit/eeb2f216739222aa1cebabd9b2dba645eb74379c))
* **settings:** add Key lifetime history dialog ([#106](https://github.com/malloc-labs/malloc-labs-copy/issues/106)) ([b703e48](https://github.com/malloc-labs/malloc-labs-copy/commit/b703e486e3c4d536165b85d5bea2827b815e331b))
* **settings:** add themed tooltips to session detail headers ([#107](https://github.com/malloc-labs/malloc-labs-copy/issues/107)) ([440d41d](https://github.com/malloc-labs/malloc-labs-copy/commit/440d41dc9f4cbaefaa5fb9b4c5bd8ca4529f42f5))
* **settings:** sync Trinkey WPM via CC1 and surface drift status ([#112](https://github.com/malloc-labs/malloc-labs-copy/issues/112)) ([43270f1](https://github.com/malloc-labs/malloc-labs-copy/commit/43270f19711d9ea40cd1d733480abb40cd62cef8))


### Bug Fixes

* **koch:** auto-uppercase exercise answer inputs ([#102](https://github.com/malloc-labs/malloc-labs-copy/issues/102)) ([3ffc6c5](https://github.com/malloc-labs/malloc-labs-copy/commit/3ffc6c5dd4d7919653e7fe19ff15c994e3667230))
* **settings:** allow horizontal scroll on rollup tables ([#104](https://github.com/malloc-labs/malloc-labs-copy/issues/104)) ([918fd22](https://github.com/malloc-labs/malloc-labs-copy/commit/918fd222d753cb9183c41b76d7e6c0663d71239f))

## [0.8.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.7.2...v0.8.0) (2026-05-18)


### Features

* **settings:** add Koch exercise diagnostics ([3bf5f76](https://github.com/malloc-labs/malloc-labs-copy/commit/3bf5f76f2e66250cc39009275fc4e52751f2f229))

## [0.7.2](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.7.1...v0.7.2) (2026-05-18)


### Bug Fixes

* **settings:** make Koch sessions table rows expandable ([#93](https://github.com/malloc-labs/malloc-labs-copy/issues/93)) ([013ddfd](https://github.com/malloc-labs/malloc-labs-copy/commit/013ddfd71ed176f1289760df27324e12d5a8b9ed))

## [0.7.1](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.7.0...v0.7.1) (2026-05-18)


### Bug Fixes

* **settings:** add tab navigation and Koch sessions table ([#91](https://github.com/malloc-labs/malloc-labs-copy/issues/91)) ([1c1cfa6](https://github.com/malloc-labs/malloc-labs-copy/commit/1c1cfa6c1977a28ce1ad3ecd2f406a5d5c7f01bc))

## [0.7.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.6.0...v0.7.0) (2026-05-18)


### ⚠ BREAKING CHANGES

* **koch:** schema_version is now 1.3 (was 1.2). KochExerciseRecord gains a required `answers` field; records written under 1.2 are no longer readable by analysis tools that target 1.3. The Koch Exercises UI removes the Stop and Clear buttons; Start doubles as Abort while a session is active.

### Features

* **koch:** capture learner answers in koch-exercise record ([#89](https://github.com/malloc-labs/malloc-labs-copy/issues/89)) ([9b6ea53](https://github.com/malloc-labs/malloc-labs-copy/commit/9b6ea535019bb5ee3c58762f185b7068a1ab918c))

## [0.6.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.5.1...v0.6.0) (2026-05-17)


### Features

* **freeplay:** custom-input section and rhythm review ([#75](https://github.com/malloc-labs/malloc-labs-copy/issues/75)) ([15745c7](https://github.com/malloc-labs/malloc-labs-copy/commit/15745c747bde4df7d919b79536e724912d3394cd))
* **koch:** Left-Alt + key previews a claimed symbol's Morse ([#81](https://github.com/malloc-labs/malloc-labs-copy/issues/81)) ([5ea0ff2](https://github.com/malloc-labs/malloc-labs-copy/commit/5ea0ff2372f680713ddf96a4d292d4de0d20c4d8))
* **koch:** play 5 ranked exercises in place of the 30s random stream ([#79](https://github.com/malloc-labs/malloc-labs-copy/issues/79)) ([a5bf0b3](https://github.com/malloc-labs/malloc-labs-copy/commit/a5bf0b384c7b3f83921776218bbb969c552f5824))
* **koch:** prepend fixed DE listening anchor to every exercise ([#80](https://github.com/malloc-labs/malloc-labs-copy/issues/80)) ([7e4fc51](https://github.com/malloc-labs/malloc-labs-copy/commit/7e4fc519eaf2d13e1e726215e815bab73bf3dc66))
* **koch:** split truth disclosure into Answers/Truth tabs ([#82](https://github.com/malloc-labs/malloc-labs-copy/issues/82)) ([ea5259c](https://github.com/malloc-labs/malloc-labs-copy/commit/ea5259c09de77ec9a7350239d46177dcbff4f610))


### Bug Fixes

* **freeplay:** align menu, sent disclosure, and preview with cadence ([#73](https://github.com/malloc-labs/malloc-labs-copy/issues/73)) ([7aef91f](https://github.com/malloc-labs/malloc-labs-copy/commit/7aef91fc271af46ad1fac51612f6e9c3025f007c))
* **freeplay:** clear button also clears review section ([#77](https://github.com/malloc-labs/malloc-labs-copy/issues/77)) ([726e3e7](https://github.com/malloc-labs/malloc-labs-copy/commit/726e3e7613cb47465c9868d5780d066d363cae74))
* **freeplay:** hide custom-input body when collapsed ([#76](https://github.com/malloc-labs/malloc-labs-copy/issues/76)) ([2183ec3](https://github.com/malloc-labs/malloc-labs-copy/commit/2183ec329fae05dc8e4b7c0a79073d0cb23c06be))

## [0.5.1](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.5.0...v0.5.1) (2026-05-16)


### Bug Fixes

* **cadence:** IMI cue + record timer-flushed sent symbols ([#71](https://github.com/malloc-labs/malloc-labs-copy/issues/71)) ([6d5003a](https://github.com/malloc-labs/malloc-labs-copy/commit/6d5003a50a6edb0119b439bcf3fd2f6e1e8ed3ff))

## [0.5.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.4.0...v0.5.0) (2026-05-16)


### Features

* **cadence:** collapsible disclosures, accel offset, sidetone speaker icon ([#69](https://github.com/malloc-labs/malloc-labs-copy/issues/69)) ([78d6d02](https://github.com/malloc-labs/malloc-labs-copy/commit/78d6d025535a1f134d0aed032a035d4ae570a331))
* **cadence:** progressive exercise ranking and Completed banner ([#68](https://github.com/malloc-labs/malloc-labs-copy/issues/68)) ([983b8de](https://github.com/malloc-labs/malloc-labs-copy/commit/983b8de10488ba1c629f43d1351842c1fd80bf65))
* **key:** Alt+symbol previews Morse on Cadence, only claimed stay bright ([#59](https://github.com/malloc-labs/malloc-labs-copy/issues/59)) ([4f6d310](https://github.com/malloc-labs/malloc-labs-copy/commit/4f6d310176c2da9d57be8322cf3d470105686cf8))
* **key:** perceptual tolerance baseline for Cadence rhythm review ([#61](https://github.com/malloc-labs/malloc-labs-copy/issues/61)) ([6e1c05c](https://github.com/malloc-labs/malloc-labs-copy/commit/6e1c05c04e6708f403f3ca2780ae4159272a96b1))
* **key:** redraw rhythm baseline every two attempts and pin tab row ([#65](https://github.com/malloc-labs/malloc-labs-copy/issues/65)) ([59199aa](https://github.com/malloc-labs/malloc-labs-copy/commit/59199aa5c945430a72fa1291e7436771df326c68))
* **key:** show N/M exercise position and collapse exercise list ([#66](https://github.com/malloc-labs/malloc-labs-copy/issues/66)) ([e9c31da](https://github.com/malloc-labs/malloc-labs-copy/commit/e9c31da006aeea1992d2dca228e2a8c415e2904d))
* **key:** single-line sent stream, dim sent symbols, E/R toggle keybinds ([#67](https://github.com/malloc-labs/malloc-labs-copy/issues/67)) ([6c5a6c5](https://github.com/malloc-labs/malloc-labs-copy/commit/6c5a6c5e966fd9e6f2af69382c264ec04c03a166))
* **key:** stack per-exercise baselines and overlay attempt markers ([#62](https://github.com/malloc-labs/malloc-labs-copy/issues/62)) ([edebde7](https://github.com/malloc-labs/malloc-labs-copy/commit/edebde79cc9a51dd82f5b46064e6a6490ef802a9))
* **key:** tabbed review with attempt-row stacking and manual new-set ([#64](https://github.com/malloc-labs/malloc-labs-copy/issues/64)) ([54aac39](https://github.com/malloc-labs/malloc-labs-copy/commit/54aac3957b75d3004b6751fd8e6bf158d1f16505))
* **session:** configurable save directory and per-mode JSON session records ([#63](https://github.com/malloc-labs/malloc-labs-copy/issues/63)) ([3e3a678](https://github.com/malloc-labs/malloc-labs-copy/commit/3e3a678461a04bed2ff42f4e51930b54789bd01f))

## [0.4.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.3.0...v0.4.0) (2026-05-15)


### Features

* **key:** "HH clears send area" developer toggle ([#54](https://github.com/malloc-labs/malloc-labs-copy/issues/54)) ([91634cb](https://github.com/malloc-labs/malloc-labs-copy/commit/91634cb0bcc3d293047f13646cacd0e49d3b8bd5))
* **key:** add S/M keyboard shortcuts and auto-rearm on tab return ([#48](https://github.com/malloc-labs/malloc-labs-copy/issues/48)) ([5dc36e9](https://github.com/malloc-labs/malloc-labs-copy/commit/5dc36e92ba96fecce8b962d833ca2c731f2baa72))
* **key:** add timing known symbols page ([d0d535a](https://github.com/malloc-labs/malloc-labs-copy/commit/d0d535ad123dd1dfbf06a0f25d08e63a465bfaeb))
* **key:** auto-advance Cadence Copy exercise on rhythmically-correct key-in ([#57](https://github.com/malloc-labs/malloc-labs-copy/issues/57)) ([024d414](https://github.com/malloc-labs/malloc-labs-copy/commit/024d41428b8bb14b0418ca5169dcfbff6118a829))
* **key:** decode measured send timing ([023a469](https://github.com/malloc-labs/malloc-labs-copy/commit/023a4690903218024763918f83a35bd22c615206))
* **key:** display decoded sent symbols ([39fef62](https://github.com/malloc-labs/malloc-labs-copy/commit/39fef622aa27766e7dc2a8542e9dadbbc68e1a53))
* **key:** enlarge Cadence Copy exercise sequence display ([#56](https://github.com/malloc-labs/malloc-labs-copy/issues/56)) ([ed7decc](https://github.com/malloc-labs/malloc-labs-copy/commit/ed7decc7f083f7a705f506c531f3edac797308e6))
* **key:** make sent-history words readable ([#49](https://github.com/malloc-labs/malloc-labs-copy/issues/49)) ([ad64ffb](https://github.com/malloc-labs/malloc-labs-copy/commit/ad64ffb2e8e678856ca83dfef0e8c52247b1fbbe))
* **key:** sentence-shaped Copy exercises with digit keybinds ([#52](https://github.com/malloc-labs/malloc-labs-copy/issues/52)) ([e5be774](https://github.com/malloc-labs/malloc-labs-copy/commit/e5be77489fe01e0fd0ec204a8722a1a84c3a6fca))
* **key:** split Key into Freeplay + Cadence, add Copy exercises ([#51](https://github.com/malloc-labs/malloc-labs-copy/issues/51)) ([f6dcc54](https://github.com/malloc-labs/malloc-labs-copy/commit/f6dcc54a61ccfde3f6477f6a5690e86160cbbf0f))
* **key:** wire Trinkey MIDI input ([5b876cb](https://github.com/malloc-labs/malloc-labs-copy/commit/5b876cbba326f7355287c6116cc6f223b54286b9))
* **midi:** add key decoder foundation ([158b039](https://github.com/malloc-labs/malloc-labs-copy/commit/158b0391bfdaa25dc7d759c6d101e9cdee909ab6))
* **settings:** add developer mode + runaway guard toggles, collapsible sections ([#45](https://github.com/malloc-labs/malloc-labs-copy/issues/45)) ([8d2ae2d](https://github.com/malloc-labs/malloc-labs-copy/commit/8d2ae2d22dc29f4e6b03b3b42714be5ea3b8829c))
* **settings:** add Trinkey buzzer option ([f007d63](https://github.com/malloc-labs/malloc-labs-copy/commit/f007d6362286395b0b5feb480688117ea784975b))


### Bug Fixes

* **key:** clean up MIDI input timing pipeline ([#50](https://github.com/malloc-labs/malloc-labs-copy/issues/50)) ([fea1351](https://github.com/malloc-labs/malloc-labs-copy/commit/fea13513651564b971170edccb6dbd3acb96a4a4))
* **key:** disable unstable live sidetone ([8f5176f](https://github.com/malloc-labs/malloc-labs-copy/commit/8f5176faec92eed95e93ebf5923e8f7459e78d80))
* **key:** only fire HH-clear on intra-word HH, not H + word-gap + H ([#55](https://github.com/malloc-labs/malloc-labs-copy/issues/55)) ([03c7011](https://github.com/malloc-labs/malloc-labs-copy/commit/03c70115488bea232d9dfd47b05b35f3126a2ba7))
* **key:** persist runaway guard server-side instead of localStorage ([#47](https://github.com/malloc-labs/malloc-labs-copy/issues/47)) ([7bf1f67](https://github.com/malloc-labs/malloc-labs-copy/commit/7bf1f677dd6d8659a36cb0fa38d627894ddb69cd))
* **key:** select Trinkey MIDI input by default ([90b02ea](https://github.com/malloc-labs/malloc-labs-copy/commit/90b02eacfc7e8c74a8b300f6bf4965a241fdbb75))


### Documentation

* **readme:** refresh browser surfaces and Settings sections ([#58](https://github.com/malloc-labs/malloc-labs-copy/issues/58)) ([5046433](https://github.com/malloc-labs/malloc-labs-copy/commit/50464338552963933f19b4a4216bb017e051bd8e))
* **readme:** refresh stale references and document recent additions ([#46](https://github.com/malloc-labs/malloc-labs-copy/issues/46)) ([dbdd955](https://github.com/malloc-labs/malloc-labs-copy/commit/dbdd955dec81eab38dfbeb6408d7f05bb018099b))

## [0.3.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.2.0...v0.3.0) (2026-05-12)


### Features

* **audio:** add signal texture settings ([47bebe1](https://github.com/malloc-labs/malloc-labs-copy/commit/47bebe1445f0bbc7de175b1879b7192cea277e06))
* **audio:** tune signal texture defaults ([b8d98b2](https://github.com/malloc-labs/malloc-labs-copy/commit/b8d98b2d25b9f88375af023c484c26a45652f356))
* **audio:** tune signal texture defaults ([88bb0ff](https://github.com/malloc-labs/malloc-labs-copy/commit/88bb0ff9e165022a0c0cac785d2e0d00811b636f))
* **settings:** add signal texture test message ([82079fe](https://github.com/malloc-labs/malloc-labs-copy/commit/82079fe215235bd9551b0b0409d435aea2e17e69))
* **settings:** add signal texture test message ([36e913d](https://github.com/malloc-labs/malloc-labs-copy/commit/36e913dc47a0ef0d1d21006a9d8ac85b41f85eaa))


### Documentation

* update settings test message readme ([c8591d6](https://github.com/malloc-labs/malloc-labs-copy/commit/c8591d672597fbad684040e4a46353fc58a794c3))
* update settings test message readme ([5dc4791](https://github.com/malloc-labs/malloc-labs-copy/commit/5dc47915074bc36cdb3d48a910345cfa50d00391))

## [0.2.0](https://github.com/malloc-labs/malloc-labs-copy/compare/v0.1.0...v0.2.0) (2026-05-12)


### Features

* **audio:** hearing-safety amplitude default and explicit output device ([b4cfc63](https://github.com/malloc-labs/malloc-labs-copy/commit/b4cfc63dc9f71484408c97effee48a56140c3f90))
* **audio:** synthesise CW symbols with raised-cosine envelope ([2a7ed06](https://github.com/malloc-labs/malloc-labs-copy/commit/2a7ed0680fbab32eb02b9203af0b2ba141635662))
* **config:** TOML config loader for AudioParameters ([a610043](https://github.com/malloc-labs/malloc-labs-copy/commit/a610043fac76af3235128909da8673c06bd1b75e))
* **guided:** add punctuation symbol exposure ([eb4bdfa](https://github.com/malloc-labs/malloc-labs-copy/commit/eb4bdfa9b8df953910b01cb0886ff23f03762bfb))
* **koch:** add word detection page ([#19](https://github.com/malloc-labs/malloc-labs-copy/issues/19)) ([e452790](https://github.com/malloc-labs/malloc-labs-copy/commit/e452790dd1cd9d472f5a5e8e07ac4280d81f244c))
* **letters:** add digit anchor support via numerals_spoken directory ([8382db6](https://github.com/malloc-labs/malloc-labs-copy/commit/8382db6636b59fc25ac886de53294d0660d8c23c))
* **letters:** module, wav loader, sequence orchestration ([c414486](https://github.com/malloc-labs/malloc-labs-copy/commit/c414486f3f0dabba8731aaa2741e17b6f9f1d3a4))
* **sequence:** per-session symbol stream generator ([52fd6be](https://github.com/malloc-labs/malloc-labs-copy/commit/52fd6bef446caed1bae2ff5239e5fc3e34ca455e))
* **server,letters:** wire play-letter WS action and frontend JS ([4dfe3cf](https://github.com/malloc-labs/malloc-labs-copy/commit/4dfe3cfac6b9d469ae2b11d4fe70f542eebdfc75))
* **server:** add word detection instruction audio ([#20](https://github.com/malloc-labs/malloc-labs-copy/issues/20)) ([3da7ba6](https://github.com/malloc-labs/malloc-labs-copy/commit/3da7ba629866b2e33cd833beed1b706d68e0735d))
* **server:** claim/start dev loop wiring sequence/ end-to-end ([3c97ae2](https://github.com/malloc-labs/malloc-labs-copy/commit/3c97ae2c158dd285df28de53ea9f33062b963ecc))
* **server:** localhost HTTP+WebSocket shell with port-bump ([7af2278](https://github.com/malloc-labs/malloc-labs-copy/commit/7af227899cc0667e00ddee4bec699915308218fc))
* **settings:** configure Koch and Farnsworth timing ([#16](https://github.com/malloc-labs/malloc-labs-copy/issues/16)) ([bdf51db](https://github.com/malloc-labs/malloc-labs-copy/commit/bdf51db77e645d5405c9f7d6a8c54e04ee65975b))
* **web:** add morse display formatter ([072981a](https://github.com/malloc-labs/malloc-labs-copy/commit/072981a4bded710aac2e781c84fa398e55cf99dc))
* **web:** add numerals 0-9 to Symbol Exposure page ([c798c3c](https://github.com/malloc-labs/malloc-labs-copy/commit/c798c3c705d25f6a7f017deba180d58617dcf7af))
* **web:** add symbol exposure truth disclosure ([974e0f6](https://github.com/malloc-labs/malloc-labs-copy/commit/974e0f6f21007ec2d982ba7cf580a6dbdf5d1630))
* **web:** centre exercises page using landing-shell composition ([3ffecab](https://github.com/malloc-labs/malloc-labs-copy/commit/3ffecaba70b58f8ffba43cbe2f8edb4cd08b3073))
* **web:** collapsible timeline disclosure + wire Stop button ([3c5fe51](https://github.com/malloc-labs/malloc-labs-copy/commit/3c5fe513ec26ebc645a2eef405f67eb8438a7c6c))
* **web:** format word detection review rows ([#21](https://github.com/malloc-labs/malloc-labs-copy/issues/21)) ([98b6471](https://github.com/malloc-labs/malloc-labs-copy/commit/98b6471ad249993abee609bd10dbc4e5504cc0a6))
* **web:** replace claim button with interactive Koch sequence token row ([cdbeb85](https://github.com/malloc-labs/malloc-labs-copy/commit/cdbeb85862ced24440171f58da265870bef13ec1))
* **web:** restructure IA — five-section nav, Copy 653 title, section landings ([8ee1a3d](https://github.com/malloc-labs/malloc-labs-copy/commit/8ee1a3d0aec97d8d896d89308b61e2dd19a81b50))
* **web:** show app version in footer ([78900f2](https://github.com/malloc-labs/malloc-labs-copy/commit/78900f2d3d0c9292ca9eed20084bc2cc25ecba93))


### Bug Fixes

* **audio:** stop audio on Stop; add Clear button ([bc535ec](https://github.com/malloc-labs/malloc-labs-copy/commit/bc535ec9f69d2e4876f05a2cc837f26d1c3e6f0f))
* **server:** allow digits in play-letter action guard ([e16690b](https://github.com/malloc-labs/malloc-labs-copy/commit/e16690b3b11aff8c4eb0b052977c7627a936ab23))
* **settings:** clarify Morse timing terminology ([#17](https://github.com/malloc-labs/malloc-labs-copy/issues/17)) ([9305520](https://github.com/malloc-labs/malloc-labs-copy/commit/9305520510e3b18601012b4f427e8b28895fcd3a))
* **settings:** enable save only for changed timing ([#18](https://github.com/malloc-labs/malloc-labs-copy/issues/18)) ([81e0bd8](https://github.com/malloc-labs/malloc-labs-copy/commit/81e0bd8ba0359afab9380c8d36caed68b4ae82a6))
* **tests:** update play-letter unknown-symbol test to use @ not digit ([e7bbd89](https://github.com/malloc-labs/malloc-labs-copy/commit/e7bbd8925d8b6c0204b140b370638c5e7b6898ea))
* **tests:** update unknown-symbol sentinel from ? to @ since ? is now a valid Koch pattern ([26f028d](https://github.com/malloc-labs/malloc-labs-copy/commit/26f028de6fc800052946c8ae3e0e0626ca02c154))
* **web:** fixed-height scrollable timeline body ([878286f](https://github.com/malloc-labs/malloc-labs-copy/commit/878286fa67c67f0f03e6205a4cefa520f0e5b572))
* **web:** prevent content jump when timeline disclosure opens ([e849924](https://github.com/malloc-labs/malloc-labs-copy/commit/e849924a5b42a5ffe199a1157f180d509f72e687))
* **web:** restore valid script closing tags in exercises.html ([3975baa](https://github.com/malloc-labs/malloc-labs-copy/commit/3975baa4dd649a2fb0d1bbd21cd956379e22dd65))
* **web:** show clock time in koch review ([#23](https://github.com/malloc-labs/malloc-labs-copy/issues/23)) ([1be4600](https://github.com/malloc-labs/malloc-labs-copy/commit/1be4600dfa1049939476bd290556e07effc8adec))
* **web:** show clock time in word review ([#22](https://github.com/malloc-labs/malloc-labs-copy/issues/22)) ([cafc65d](https://github.com/malloc-labs/malloc-labs-copy/commit/cafc65df762c4896fa8958a648b00b0e7fec5503))


### Documentation

* add CLAUDE.md for AI assistant onboarding ([943a776](https://github.com/malloc-labs/malloc-labs-copy/commit/943a776b901ab68a4331ffc6fa6e62843356abd9))
* add philosophy and specification ([4b6f96f](https://github.com/malloc-labs/malloc-labs-copy/commit/4b6f96f40dd69f84934db48d3a9fc1e5e96f8bcf))
* refresh current app documentation ([#24](https://github.com/malloc-labs/malloc-labs-copy/issues/24)) ([97a64c7](https://github.com/malloc-labs/malloc-labs-copy/commit/97a64c7026d00fe37875361bdc05f87c708c5721))
* refresh README and CLAUDE.md after server slice ([33492af](https://github.com/malloc-labs/malloc-labs-copy/commit/33492afe269642192670c1d3585a1b5c1740ea21))

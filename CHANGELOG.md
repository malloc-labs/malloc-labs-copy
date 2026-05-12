# Changelog

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

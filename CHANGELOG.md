# Changelog

## [2.0.0](https://github.com/tjbaker/ha-schluterditraheat/compare/v1.1.0...v2.0.0) (2026-10-01)


* release 2.0.0 ([c13f70e](https://github.com/tjbaker/ha-schluterditraheat/commit/c13f70e43a822d68d0113ee30f8d227d1a18bb81))


### Features

* add a per-device Refresh button; cite Sinope's 300s polling ask ([eda4b87](https://github.com/tjbaker/ha-schluterditraheat/commit/eda4b870c43c2854eb60acc4357555f41f64e777))
* add diagnostics with a health analysis ([#4](https://github.com/tjbaker/ha-schluterditraheat/issues/4)) ([26826d6](https://github.com/tjbaker/ha-schluterditraheat/commit/26826d6a27145595523e348abaa387353820a6f2))
* add power sensor and energy dashboard statistics ([04a5580](https://github.com/tjbaker/ha-schluterditraheat/commit/04a5580810188dec442da2ffc140c0e79c539622))
* add power sensor and energy dashboard statistics ([1469c5a](https://github.com/tjbaker/ha-schluterditraheat/commit/1469c5a9f1fda804b1491365a3101991841066a9))
* expose device metadata and a Wi-Fi signal sensor ([c6ab091](https://github.com/tjbaker/ha-schluterditraheat/commit/c6ab09164c516ae325208d042e193c58621df407))
* header-driven rate limiting and JSON error-code handling ([2f92311](https://github.com/tjbaker/ha-schluterditraheat/commit/2f92311942777aeb03da6cb0a76b00d1561dde7a))
* merge upstream PRs [#3](https://github.com/tjbaker/ha-schluterditraheat/issues/3)-[#6](https://github.com/tjbaker/ha-schluterditraheat/issues/6) (energy, power, rate limits, metadata) ([98d73c8](https://github.com/tjbaker/ha-schluterditraheat/commit/98d73c8e1ad1c7711d4e6c66d3c89ea6e015b20f))


### Bug Fixes

* address review feedback on energy and power support ([7fb7002](https://github.com/tjbaker/ha-schluterditraheat/commit/7fb7002cca2d88ecb0d902576bb5cd9abfaa5c9b))
* pause the energy import when the daily request cap is hit ([feb3baf](https://github.com/tjbaker/ha-schluterditraheat/commit/feb3bafd2e0bfa17bd0691781c6784727622f23b))
* power sensor reports full load when heating, not load x percent ([b56c326](https://github.com/tjbaker/ha-schluterditraheat/commit/b56c326b56987b13b6746c5c0542087418f08a15))
* specify mean_type when importing energy statistics ([83be346](https://github.com/tjbaker/ha-schluterditraheat/commit/83be346a7a064ef8a2f73ad9dcc9461a80db7eb1))
* specify unit_class when importing energy statistics ([35519b9](https://github.com/tjbaker/ha-schluterditraheat/commit/35519b9735655ee902ce54bdd578d9e0bd9a1a7a))
* stop leaking Schluter sessions and don't reauth on the session cap ([#7](https://github.com/tjbaker/ha-schluterditraheat/issues/7)) ([584ed31](https://github.com/tjbaker/ha-schluterditraheat/commit/584ed3177428635fe17182ddd965d73d991b695f))


### Code Refactoring

* log raw device attributes once per poll ([cc17b7a](https://github.com/tjbaker/ha-schluterditraheat/commit/cc17b7a58c7b12b537f4700a54aa64355bca0ea5))
* type coordinator data and energy statistics for mypy ([23afb84](https://github.com/tjbaker/ha-schluterditraheat/commit/23afb84c3477069400d1066d7a795eea6428276d))

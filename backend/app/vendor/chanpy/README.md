# chan.py computation core

Source: https://github.com/Vespa314/chan.py

Pinned revision: `f8ca3b5e44d7166e2abd756a8e7fa816c79faebe`.

MIT license and upstream copyright notice are preserved in LICENSE.
UPSTREAM.json lists the original source hashes. Only computation modules are
included, without data-source clients, plotting, model training or trading.
Imports are namespaced under `app.vendor.chanpy` to avoid polluting sys.path or
colliding with unrelated packages. Calculation code is unchanged.

The application adapter uses CChanConfig, CKLine_List and CKLine_Unit directly.
It supplies normalized project OHLC values, and never invokes upstream data
providers. For upgrades compare the pinned source manifest, reapply only the
namespace rewrites, and run tests/test_chan_analysis.py and graph/page tests.

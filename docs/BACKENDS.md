# Lighting backends

This document covers the lighting backend interface and the adapters currently
compiled into `rgbcd`. [API.md](API.md) is the source of truth for API v1
operations, schemas, capability names, and errors.

## `LightingAdapter` contract

`src/adapter.hpp` defines one abstract interface with four methods:

```cpp
virtual QJsonObject engine() const = 0;
virtual QJsonArray devices() const = 0;
virtual Protocol::Reply lighting(const QString &device) const = 0;
virtual Protocol::Reply setLighting(const QString &device,
                                    const QString &color,
                                    int brightness) = 0;
```

- `engine()` returns the backend's current API `Engine` object.
- `devices()` returns the current API `Device` records owned by the backend.
- `lighting(device)` returns the current API `Lighting` value or a structured
  `Protocol::Reply` error.
- `setLighting(device, color, brightness)` applies the API-validated static
  colour and brightness, then returns the resulting `Lighting` value or an
  error.

The interface is a C++ boundary, not permission to extend the wire format.
Implementations must use the types, closed capability strings, error codes,
and write semantics already specified in [API.md](API.md), unless that
contract is deliberately updated together with both clients and the daemon.

## Existing adapters

| Adapter | `engine()` | `devices()` | `lighting()` | `setLighting()` |
|---|---|---|---|---|
| `DemoAdapter` | Ready simulation status | One simulated device | In-memory read | In-memory write |
| `OpenRgbAdapter` | Cached OpenRGB status | Cached candidate/controller records | Direct call returns `unavailable`; the server uses `perform()` | Direct call returns `unavailable`; the server uses `perform()` |

### Demo

`DemoAdapter` is selected by `rgbcd --demo`. It supplies one writable device,
`demo:rgb0`, with exactly `lighting.read`, `lighting.write`, and `brightness`.
Colour and brightness live only in the adapter instance. It also supplies the
demo sensor snapshot through its separate `sensors()` method. `DemoAdapter`
itself contacts no hardware, OpenRGB process, or system D-Bus service. The
surrounding `rgbcd --demo` server still serves `profile.get` and `profile.set`
through `PowerProfiles`, which uses `power-profiles-daemon` on system D-Bus.

### OpenRGB

`OpenRgbAdapter` is the normal adapter. Its public cache is updated by an
`OpenRgbWorker` on a dedicated Qt thread. `Server::dispatchLighting()` sends
`devices`, `devices.rescan`, `lighting.get`, and `lighting.set` to the worker
through `perform()` and replies from the asynchronous callback.

The four base-interface methods still exist. `engine()` and `devices()` read
the cache. The synchronous `lighting()` and `setLighting()` methods
intentionally return `unavailable`, because real SDK traffic must not block
the API thread. This is an implementation-specific extension around the
minimal base interface, not an additional API v1 operation.

OpenRGB capability states are derived from runtime evidence:

| State | Exposed lighting capabilities | Writable |
|---|---|---|
| Udev-rule candidate before an SDK descriptor is available | None | No |
| Controller with a decodable uniform current colour | `lighting.read` | No, unless every write gate also passes |
| Enabled, uniquely identified, nonexcluded controller with a supported `Static` colour mode | `lighting.read`, `lighting.write`, `brightness` | Yes |
| Excluded controller | None | No |
| Other nonwritable device | Decoded capabilities only; often none | No |

Brightness may be native to the OpenRGB mode or emulated by scaling the
uniform colour. The returned `brightness_emulated` field reports which path
was used. A successful write is followed by a controller read; a mismatch is
an error rather than an assumed success.

## Adding an adapter

1. Implement all four methods in `LightingAdapter`. Keep engine and device
   ownership deterministic and return `Protocol::Reply` errors rather than
   ad-hoc JSON failures.
2. Emit only API fields and values defined by [API.md](API.md). If the backend
   needs a new operation, type, capability, or error, update the API contract,
   daemon, UI, and tests together before advertising it.
3. Add selection and lifetime management in `Server::initializeAdapters()`.
   The current server has explicit demo/OpenRGB branches and OpenRGB-specific
   casts for worker, subscription, hotplug, and idle handling. A third normal
   backend must either provide equivalent routing or first replace those casts
   with an explicit asynchronous backend abstraction.
4. Map `devices`, `devices.rescan`, `lighting.get`, and `lighting.set` to the
   adapter without blocking the API thread. Preserve the API's scan and write
   rate limits and subscription behavior.
5. Start with every device read-only. Add `lighting.read` only when the backend
   can return a valid `Lighting` value. Add `lighting.write` and `brightness`
   only after all identity, exclusion, opt-in, and backend-mode gates pass.
6. Confirm writes by reading state back when the backend permits it. Return
   `blocked`, `unsupported`, or `unavailable` according to the API contract;
   do not turn backend uncertainty into a capability claim.
7. Add adapter tests for discovery, malformed data, capability gates,
   unavailable devices, rate limits, and successful reads/writes. Hardware
   claims require separate evidence; a simulated backend proves only the
   simulated path.

## Backend rules

- [API.md](API.md) wins. Adapter convenience fields or engine terminology do
  not change the public contract.
- Never invent capabilities. `capabilities` is a statement of operations that
  work now for that device, not a wish list or a copy of upstream marketing.
- `writable: true` requires every documented gate; discovery alone is never
  sufficient.
- Do not bypass the per-device confirmation by changing `devices.json`
  implicitly. The UI owns the opt-in choice; the daemon and launcher consume
  it defensively.
- Do not add firmware-save commands or broaden device access as an adapter
  implementation detail. Such a change requires an explicit API, security,
  UI-confirmation, and documentation review.


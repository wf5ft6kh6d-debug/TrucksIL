# Product requirements — draft v0.2

_Updated 2026-11-14. v0.1 content is kept and expanded into user stories._

## Users
Truck drivers operating in Israel. Account and multiple editable truck profiles.

## Safety principles

These override any story below.

1. **Absence of data ≠ safe.** A road with no known restriction is "unknown", never "suitable". Coverage gaps are shown to the driver.
2. **Unverified data is a warning, never a permission.** Only `verified`, unexpired evidence may support a positive route decision. `unverified`, `disputed` and `expired` data, OSM candidates and driver reports can only add warnings or avoidances.
3. **Posted signs are shown exactly as posted.** The driver-facing value is the sign value, unrounded and unconverted; measured clearance never silently replaces it.
4. **Hard restrictions are enforced** against the active vehicle profile. When in doubt, be conservative.
5. **No route guidance until safety gates pass** (see ROADMAP stage 3).
6. **No legal certification.** Route and shift timer outputs do not certify legal compliance.

## Priority key (MoSCoW)
**M** must (MVP), **S** should, **C** could, **W** won't (this release).

## User stories

### US-01 Vehicle profile — M
As a driver, I want to save one or more truck profiles so routes match my vehicle.
- Fields: height, width, length (m), gross weight, optional axle load (t), optional hazmat (ADR) class; validated by `data/vehicle-profile.schema.json`.
- Out-of-range or missing required values block saving, with a field-level message.
- Units shown with every value; no implicit unit conversion.
- The active profile is visible on the route screen; changing it recalculates the route.

### US-02 Route with restrictions — M
As a driver, I want a route that respects my truck's dimensions and weight.
- No route segment violates a `verified` hard restriction for the active profile.
- If no compliant route exists, the app says so; it never returns a violating route as normal.
- Route details list every restriction considered on the route, with status and source.
- Disabled for end users until safety gates pass.

### US-03 Unknown-coverage warnings — M
As a driver, I want to know where the app has no restriction data.
- Segments without verified data for a relevant restriction type are marked "no data" on the map and in route details.
- The route summary shows the share/length of unknown coverage.
- Unverified/disputed/expired restrictions on the route appear as warnings, never as clearance.
- Wording never implies "no data" means "allowed".

### US-04 Posted-sign height display — M
As a driver, I want to see the clearance exactly as written on the road sign.
- When `valueSource = posted_sign`, the value is shown exactly as on the sign (same digits, unit, no rounding or conversion).
- Source name and observation/verification date are shown next to the value.
- Measured or derived values are labelled as such and never presented as the sign value.
- `valueSource = unknown` is shown as an unconfirmed value with a warning.

### US-05 Driver reports — S
As a driver, I want to report traffic, accidents, hazards and wrong restriction data.
- Reports are labelled "unverified user report", carry a time-to-live and expire automatically.
- Reports enter moderation; they can never be promoted to official notices.
- Rate limiting and abuse protection apply.
- Official police/transport updates come only from authenticated official sources, with separate attribution (C for MVP).

### US-06 Shift timer — S
As a driver, I want to track my shift and be warned before my limit.
- Start / break / resume / end; user-configurable limit.
- Alerts at 2 h, 1 h and 30 min before the limit when applicable.
- Shows a "not legal compliance certification" disclaimer.
- Works offline; state survives app restart.

### US-07 Languages and RTL — M
As a driver, I want the app in my language.
- Hebrew (RTL), Arabic (RTL), Russian, English, switchable in settings.
- All screens render correctly in RTL, including maps controls, numbers and units.
- Sign values (US-04) are not altered by localisation.
- No hard-coded user-facing strings.

### US-08 Privacy — M
As a driver, I want control over my location data.
- Explicit consent before location access; the app is usable for profiles without location.
- Minimal location retention, with a documented retention period.
- The user can delete account and location history.
- Privacy policy and retention/deletion policy are published before release (Israeli Privacy Protection Law reviewed).

### Out of scope for this release — W
- CarPlay / Android Auto (requires separate platform-policy review).
- Turn-by-turn voice navigation before safety gates pass.

## Platforms
Android, iPhone. Platform choice (PWA first vs native/cross-platform) is an open decision.

# Product requirements — draft v0.1

## Users
Truck drivers operating in Israel. Account and multiple editable truck profiles.

## Vehicle profile
Height (m), width (m), length (m), gross weight (t), optional axle load (t), hazardous goods classification where relevant. Units and validation required.

## Routing
Use road graph and restriction evidence. Hard restrictions must be enforced; unknown coverage must be surfaced, not treated as permission. Route details must disclose limitations. No route guidance until safety gates pass.

## Reports and alerts
Driver-submitted traffic, accidents, hazards, and camera reports are unverified user reports. Official police and transport updates must be ingested only from authenticated official sources and clearly attributed. Moderation and expiration required.

## Shift timer
Start / break / resume / end; user-configurable shift limit; alerts 2h, 1h, 30m before limit when applicable. Do not present the timer as legal compliance certification.

## Platforms and languages
Android, iPhone; Hebrew (RTL), Russian, Arabic (RTL), English. CarPlay / Android Auto feasibility requires separate platform-policy review.

## Privacy
Minimize location retention; obtain consent; protect location and account data; define retention and deletion policy before release.

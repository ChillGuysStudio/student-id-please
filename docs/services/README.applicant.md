# Applicant service

Applicant owns profile presets and immutable presented claims for a case.

## Public image

The image is [`mcittkmims/applicant-service`](https://hub.docker.com/r/mcittkmims/applicant-service/tags). The `APPLICANT_SERVICE_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8081`.

Source code is in the [private repository](https://github.com/mcittkmims/applicant-service). Public images run without private-source access.

## Dependencies

The service needs MongoDB with a replica set, Session context, and the pinned university snapshot.

The `applicant` database belongs to this service even when MongoDB infrastructure is shared.

As an initializer, Applicant publishes only its claims section. As a subscriber, it derives claims from the received evidence and snapshot.

Mocked peers supply the same snapshot, identity, and Session shapes as real peers. They do not supply a prebuilt complete case for every service.

Integrated generation preserves identity reservations and verifies all case owners become ready.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `MONGODB_URI` identifies the service database and replica set.
- The CPR Compose file supplies the shared MongoDB address.
- Peer URLs and caller credentials follow the private service configuration.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Applicant Postman collection](../../postman/applicant-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.

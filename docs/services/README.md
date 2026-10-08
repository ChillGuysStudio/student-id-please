# Service references

| Service | Public image | Local API | Reference |
| --- | --- | --- | --- |
| Player | `tirppy/student-id-player-service` | `8001` | [Player](README.player.md) |
| Session | `tirppy/student-id-session-service` | `8002` | [Session](README.session.md) |
| Applicant | `mcittkmims/applicant-service` | `8081` | [Applicant](README.applicant.md) |
| Credential | `mcittkmims/credential-service` | `8082` | [Credential](README.credential.md) |
| Server Rules | `maxnoragami/server-rules-service` | `8005` | [Server Rules](README.server-rules.md) |
| University Record | `maxnoragami/university-record-service` | `8006` | [University Record](README.university-records.md) |
| Moderation | `sentientmoss/pad-moderation-service` | `8008` | [Moderation](README.moderation.md) |
| Discord DMs | `sentientmoss/pad-discord-dms-service` | `8009` | [Discord DMs](README.discord-dms.md) |

The current [Compose configuration](../../compose.yaml) binds these service ports to localhost and does not yet wire the gateway. Database and broker ports stay on the container network.

The Lab 2 target uses shared Go gateway infrastructure for public REST, REST realtime negotiation, and internal service-to-service REST. After negotiation, clients connect directly to Discord DMs for the WebSocket upgrade and frames. The gateway owns no domain data. The [interaction map](../architecture.md#communication) shows logical callers and receivers, and [gateway delivery status](../architecture.md#gateway-delivery-status) distinguishes the approved foundation from pending integration and image verification.

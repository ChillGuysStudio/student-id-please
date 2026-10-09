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

The Lab 2 target sends all client-to-service REST through the shared Go gateway's public listener and all service-to-service REST through its internal listener. Realtime negotiation and chat-ticket REST use the gateway. After negotiation, clients connect directly to Discord DMs for the WebSocket upgrade and frames. Broker events and service-owned storage connections are not REST paths. The gateway owns no domain data. The [interaction map](../architecture.md#communication) records these routes, and [gateway authorization](../architecture.md#gateway-authorization) describes identity checks and service permissions. The [architecture diagram](../architecture.png) shows these routes, with RabbitMQ greyed as Lab 4 scope.

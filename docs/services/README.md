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

The [Compose configuration](../../compose.yaml) binds these ports to localhost. Database and broker ports stay on the container network. The gateway is separate infrastructure.

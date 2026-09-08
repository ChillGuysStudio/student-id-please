# Topic 3 - Student ID, please

## Service Boundaries

Each service is the only writer to the data it owns. Other services use APIs to request that data or consume events containing the data they need. Data copied into a local projection does not become a new source of truth.

### Player Service

The Player Service owns:

- player accounts and authentication
- player profiles and friendships
- moderation teams and team membership
- XP, levels, and persistent progression

It updates progression from completed-shift and disciplinary events. It does not own applicants, moderation-session roles, admission decisions, or session scores.

### Server Moderation Session Service

The Server Moderation Session Service owns:

- moderation-shift creation and lifecycle
- the participant roster and the Moderator or Junior Moderator role assigned to each participant
- the current applicant reference
- the number of processed applications
- the aggregate shift score and penalties

It consumes individual outcomes from the Moderation Service and calculates the overall shift result. When a shift ends, it publishes the result for the Player Service to apply to player progression.

It does not own player accounts or progression, applicant details, individual admission decisions, server rules, or chat messages.

### Applicant Service

The Applicant Service owns the applicant profile and the claims presented by the applicant. These claims can include the applicant's name, student ID, major, year, university status, courses, and role.

An applicant can claim to be a FAF student, a student from another major, a teaching assistant, a university staff member, an alumnus, or an outsider. The claims may be false or may impersonate another person.

The service does not own submitted credentials, authoritative university records, credential-validation results, or admission decisions.

### Credential Service

The Credential Service owns:

- documents and credentials presented by an applicant
- structural and authenticity checks
- the validation result for each credential

Credentials can include a student ID, a university email, an enrollment confirmation, or an ELSE course registration. A credential can be expired, forged, inconsistent, or incomplete.

The service does not own the applicant's claimed identity, authoritative university records, access rules, or admission decisions. A valid credential does not by itself grant access to the Discord server.

### Server Rules Service

The Server Rules Service owns versioned rules for accessing the Discord server. It evaluates applicant claims, credential results, university facts, and moderation history against the rule version active for the shift.

Rules can restrict access by major, year, enrollment duration, university role, allowed channels, or an existing ban. The service returns the expected policy result and the rules that matched.

It does not own applicant data, credentials, university records, bans, moderator actions, or scoring. The Moderation Service owns the comparison between the expected policy result and the Moderator's decision.

### University Record Service

The University Record Service owns authoritative university facts, including:

- current enrollment
- Outlook group email membership
- existing courses
- the current academic year
- the semester schedule
- FCIM server message records

It also owns permissions that determine which university records each Junior Moderator may inspect. The service enforces these permissions whenever a player requests a record.

It does not own applicant claims, submitted credentials, credential-validation results, or admission decisions.

### Moderation Service

The Moderation Service owns:

- the Moderator's Accept, Reject, Flag, or Ban action for each applicant
- decision history and active bans
- the server-rule result used for the decision
- the correctness, violated rules, outcome, and penalty for one decision

The service obtains the required facts from the Applicant, Credential, University Record, and Server Rules services. It compares the Moderator's action with the result returned by the Server Rules Service, then publishes the decision outcome to the Server Moderation Session Service.

It does not own the source applicant data, credentials, university records, rule definitions, or aggregate shift score.

### Discord DMs Service

The Discord DMs Service owns moderation channels, channel membership, messages, and real-time message delivery over WebSockets. Session channels can include:

- `#enrollment-check`
- `#faculty-check`
- `#course-registration`
- `#general-mod-chat`

The service uses session roles and university-record permissions when granting channel access. It does not own those roles or permissions. It transports messages but does not verify whether their contents are correct.

### Applicant case initialization

The Applicant, Credential, or University Record service may receive the first request for a new applicant case. The first service creates a shared applicant case ID and publishes a case-initialized event with the generation data. Each receiving service then creates only the records it owns.

No service writes directly to another service's database. The shared case ID links the applicant profile, credentials, university records, moderation decision, and session entry without creating shared data ownership.

## Architecture Diagram

<img src="docs/architecture.svg" alt="Architecture Diagram" width="1080"/>


## Contribution & Workflow Guidelines

### Branching Model

We follow a Gitflow-inspired branching model with `main`, `dev`, and short-lived feature/task branches:

```text
main (stable / production releases)
 └── dev (integration of current lab)
      ├── feat/lab-X/service-or-feature
      ├── fix/lab-X/issue-description
      ├── docs/lab-X/update-description
      └── chore/lab-X/task-description
```

#### Naming Conventions

- **`main`**: Production-ready state. Only receives merges from `dev` upon lab completion.

- **`dev`**: Active integration branch for the current laboratory work.

- **Feature Branches**: `feat/lab-X/service-or-feature`
    - *Example:* `feat/lab-1/player-auth`

- **Fix Branches**: `fix/lab-X/issue-description`
    - *Example:* `fix/lab-0/submodule-link-error`

- **Documentation Branches**: `docs/lab-X/update-description`
    - *Example:* `docs/lab-0/communication-contracts`


- **Chore Branches**: `chore/lab-X/task-description`
    - *Example:* `chore/lab-0/update-submodules`


### Commit Conventions

Our commit strategy is strictly based on the **[Conventional Commits v1.0.0](https://www.conventionalcommits.org/)** specification to maintain a clean and readable git log.

**Commit Format:**
`<type>(<scope>): <short summary in imperative mood>`

* **`feat`**: Used when introducing a brand-new feature or service functionality.
  * *Example:* `feat(game-service): implement websocket cycle timer`
* **`fix`**: Used when patching a bug, error, or unwanted behavior in the codebase.
  * *Example:* `fix(user-service): fix jwt token expiration validation`
* **`docs`**: Used exclusively for documentation updates (README files, architecture diagrams, API specifications).
  * *Example:* `docs(readme): add contribution and workflow rules`
* **`style`**: Used for code style/formatting changes that do not affect logic (white-space, semi-colons, formatting).
  * *Example:* `style(player-service): format files according to prettier rules`
* **`refactor`**: Used for rewriting or restructuring code without changing existing behavior or adding features.
  * *Example:* `refactor(resource-service): extract database connection logic into helper module`
* **`test`**: Used when adding missing unit/integration tests or updating existing test suites.
  * *Example:* `test(exam-service): add unit tests for grade calculation endpoints`
* **`chore`**: Used for routine maintenance, build configuration, dependency updates, or git submodule management.
  * *Example:* `chore(submodules): link private user-service repository`


### Merge Strategy

- **Feature --> `dev`**: Use *Squash and Merge* to maintain a clean, linear history of completed tasks on the integration branch.

- **`dev` --> `main`**: Use *Rebase and Merge* upon final lab evaluation to preserve full milestone history.


### Versioning Strategy

Versions are tagged exclusively on `main` upon completing lab checkpoints or hotfixes:

* **Major Lab Releases (`vX.0.0`):** Created when merging `dev` into `main` after completing all lab requirements (e.g., `v0.0.0`, `v1.0.0`, `v2.0.0`).
* **Hotfixes (`vX.0.Y`):** Created if fixes are required on `main` (e.g., `v1.0.1`).

### Pull Request Format

#### PR Naming Convention
PR titles must follow the Conventional Commits scope pattern:  
`<type>(lab-X): <short imperative summary>`

* **Example:** `docs(lab-0): define architecture diagram and workflow rules`
* **Example:** `feat(lab-1): implement JWT authentication in player service`

#### PR Description Template
All PRs targeting `dev` or `main` must use the following structured format:

```markdown
## Why?
[Explain the goal or problem this PR addresses]

## Changes
[Brief overview of the technical approach/implementation and changes included]

## How to Test?
[Provide step-by-step instructions on how reviewers can verify these changes]

## Screenshots / Evidence (Optional)
[Attach screenshots, API test output, or logs if applicable]
```

#### PR Reviewing Process

- **Minimum Approvals & Reviewers**: At least one
- **Automated Checks**: All CI pipelines and tests must pass before merging
- **Review Criteria**:
  - Code quality, readability, and modularity
  - Adherence to branch and commit naming standards
  - Test coverage and endpoint functionality
  - Security considerations and secret protection


### Example Lab Workflow

**1. Task Development**
* Branch off `dev`: `git checkout -b <type>/lab-X/<description>`
* Commit changes: `git commit -m "<type>(<scope>): <summary>"`
* Push and open PR targeting `dev`

**2. Peer Review & Integration**
* Request at least 1 peer approval
* Verify CI checks, submodule pointers, and lack of secrets
* Merge into `dev` using **Squash and Merge**

**3. Lab Completion & Release**
* Open PR from `dev` to `main` when lab requirements are met
* Perform final testing and submission verification
* Merge into `main` using **Rebase and Merge**
* Tag release on `main`: `git tag -a vX.0.0 -m "Lab X completion"` && `git push origin vX.0.0`

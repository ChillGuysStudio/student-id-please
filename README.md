# Topic 3 - Student ID, please

## Service Boundaries

### Player Service

Responsible for the identity of the players themselves. Stores **accounts, authentication, profiles friends and XP/Levels** within the game.

Players can form “moderation teams” and join server moderation sessions. The service tracks persistent progression
through leveling based on moderator experience, completed shifts and disciplinary actions.

The service does not contain information about the people attempting to join the university server.


### Server Moderation Session Service

Manages an active **Discord moderation session**.

A session represents one moderation shift and contains a **Moderator** and several **Junior Moderator** players.

It is responsible for:
- creating and joining sessions
- assigning roles
- starting/ending shifts
- current applicant
- number of applications processed
- session score and penalties

At the end of a shift, the service determines the overall session result and publishes the results for player progression.


### Applicant Service

Owns the people attempting to access the server. Generates applicants with information such as **name student ID, major, year, university status, courses and role etc**.

Applicants may be:
- students of FAF
- students from other majors
- teaching assistants
- university staff
- alumni
- outsiders

Some applicants may intentionally provide false information or attempt to impersonate another person.

If the Applicant Service is contacted first for a new applicant, it initializes the applicant's profile and propagates the relevant information to the Credential and University Record Services.

Otherwise, it generates the profile based on the information provided by whichever service initialized the applicant.


### Credential Service

Owns the documents and credentials presented by applicants.

Examples include:
- student ID
- university email
- enrollment confirmation
- ELSE course registration etc

Credentials can be expired, forged, inconsistent or incomplete.

The service validates the structure and authenticity of credentials but does not decide whether the applicant should be admitted to the Discord server.

If the Credential Service is contacted first for a new applicant, it initializes the applicant's documents and propagates the relevant information to the Applicant and University Record Services. Otherwise, it generates the documents based on the information provided by whichever service initialized the applicant.


### Server Rules Service

Owns the current rules for accessing the major's Discord server.

Rules can change between shifts and can become increasingly complicated.

Examples:
- only FAF students may join
- first-year students may access #general
but not #dark-memes or #groapa
- students must be enrolled in FAF for at
least 2 years
- professors may access the teacher
channels
- previously banned students cannot
enter regardless of their credentials

The service evaluates applicants against the current access rules.


### University Record Service

Provides the hidden university information that moderators may need to verify an applicant.

Examples include:
- current enrollment list
- the Outlook Group Lists of emails
- current existing courses
- current academic year
- schedule for the semester
- FCIM server message record etc

This information is deliberately distributed among the junior mod players. One player might have access to enrollment list while another can inspect the FCIM server.

Players must not be able to access records they were not assigned to see.

If the University Record Service is contacted first for a new applicant, it initializes the records containing the applicant and propagates the relevant information to the Applicant and Credential Services. Otherwise, it generates the student records based on the information provided by whichever service initialized the applicant.


### Moderation Service

Owns the actual admission decision for each applicant.

The Moderator can choose actions such as:
- **Accept** — allow the applicant into the Discord server
- **Reject** — deny access
- **Flag** — send the applicant for further investigation
- **Ban** — permanently prevent access

The service gathers the relevant information and determines whether the
decision was correct according to the current server rules. It records the applicant, decision, violated rules, penalties and outcome.


### Discord DMs Service

Provides the real-time communication between the moderator and the junior mods.

Players communicate through a Discord-like interface using WebSockets. The service manages channels associated with the current moderation session.

For example:
- `#enrollment-check`
- `#faculty-check`
- `#course-registration`
- `#general-mod-chat`

Different players can have access to different channels/information. The service transports messages but does not determine whether information is correct.

## Architecture Diagram

<img src="docs/architecture.svg" alt="Architecture Diagram" width="1080"/>

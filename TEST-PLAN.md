# UP Drive V2 automated test plan

## Scope

Core feature: a passenger creates and manages a ride request in the corrected
UP Drive repository: https://github.com/phathon2006/-UP-drive

The application supports Create, Read, and cancellation (a status update).
There is no ride-request Delete endpoint, so these four cases are not a full
CRUD suite.

## Cases

| ID | Action | Expected result |
| --- | --- | --- |
| TC-01 | Submit a valid ride from the passenger page; map coordinates are fixed test fixtures | UI confirms creation; HTTP 201; response contains the new ride ID and passenger ID |
| TC-02 | Reopen the passenger page and read the ride created in TC-01 | UI shows the saved route; HTTP 200; stored values match the created ride |
| TC-03 | Cancel that ride from the passenger page | UI confirms cancellation; HTTP 200; a subsequent read shows status cancelled |
| TC-04 | Try to create a ride with an empty origin | Browser required-field validation blocks submission; a direct API check returns HTTP 400 |

TC-01 through TC-03 use the same ride. TC-03 leaves the ride in a cancelled
state. If an earlier case fails, teardown attempts to cancel any ride created
by this run. Existing rides belonging to the account are left alone.

## Setup

1. Run npm install in this repository.
2. Copy .env.example to .env and set the project URL and API keys. Keep the
   secret key on the server only. .env is ignored by Git.
3. Set the email and password of a passenger account reserved for these tests.
4. Install test dependencies with python -m pip install -r requirements-test.txt.
5. Start the application with npm start.
6. In another terminal run npm run test:e2e.

The runner writes a JSON summary to test-results/ride-request-results.json
and records one Playwright browser video per case in test-results/videos/TC-01.webm
through TC-04.webm. The browser opens with the test account session already
loaded, so credentials do not appear in the videos. The test-results/ directory
is ignored by Git.

## Database note

The existing Supabase project was checked read-only for the columns used by
this version of the ride-request feature. Do not run supabase.sql against
that shared project as a setup step: it drops the existing application tables
before recreating them. Use that SQL only when deliberately initializing a
separate, empty database or after a planned backup and migration.

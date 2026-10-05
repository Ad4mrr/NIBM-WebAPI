# API Design and Viva Study Guide

This is an explanation aid, not report prose. Read the code, run the examples,
and explain the decisions in your own words.

## Why there are three caller types

An installation is a write client. Its JWT contains `installation:write` and an
exact installation ID. The POST route compares that claim with the path ID, so
a token for installation 1 cannot write to installation 2.

National, provincial, and district users are read clients. Their JWT has
`analyst:read`; database queries also add the jurisdiction condition. The scope
answers "may this actor read?" and the jurisdiction answers "which rows?".

The catalog administrator is a control-plane role used to demonstrate correct
CRUD on mutable geography and asset metadata. It cannot submit readings.

## Why readings cannot be updated or deleted

`GenerationReading` is an append-only time series. Allowing PUT, PATCH, or
DELETE would contradict the data model and could silently rewrite history.
Metadata resources have full CRUD, while reading mutation returns 405. This is
the project's defensible interpretation of the brief's ambiguous CRUD wording.

## How conditional requests work

Mutable rows have a `version` number. Their ETag contains that version. A GET
with a matching `If-None-Match` returns 304 with no body. An update with a stale
`If-Match` returns 412, preventing a client from overwriting a newer change.

Collections and derived resources do not have one row version, so their ETag is
a SHA-256 hash of the returned representation.

## How the district summary avoids a common mistake

The current-power value uses the latest reading per installation and ignores a
reading older than 30 minutes. Today's energy does not sum cumulative meter
values. It subtracts each installation's first value after Sri Lankan midnight
from its latest value, then adds those per-installation differences.

## Richardson maturity placement

The API uses nouns/resources, HTTP methods, status codes, and headers, so it is
at Richardson Level 2. It does not provide hypermedia controls that guide a
client to every possible next action, so it honestly stops short of Level 3.

## Useful demonstration sequence

1. Sign in as the Colombo analyst and show that Colombo works while Galle is
   hidden with 404.
2. Retrieve `/api/v1/provinces`, copy the ETag, and repeat with
   `If-None-Match` to show the empty 304.
3. Sign in as `SL-COL-001`, create a reading for installation 1, and show 201
   plus Location.
4. Reuse that device token against installation 2 and show 403.
5. Query `/api/v1/readings` with time, district, page, and sort parameters.
6. Show the installation overview and district generation summary.
7. Try deleting a reading and explain the 405 append-only response.

## Limitation to discuss honestly

The coursework token endpoint is deliberately small; production identity would
normally be delegated to a real authorization server with key rotation,
revocation, audit logging, rate limiting, and managed secrets. The API uses
signed JWTs and proper scope/attribute enforcement without pretending to be a
complete OAuth platform.

# Public Workshop, Brand Engagement, and Idempotency

> Executable contracts for creator publishing, audience projection, brand
> collaboration, authenticated writes, and Agent SSE turns.

---

## Scenario: Public Workshop and Brand Collaboration

### 1. Scope / Trigger

- Trigger: changing a Workshop field, visibility rule, published snapshot,
  brand membership, authorization, discovery filter, follow, interest, inbox
  event, authenticated mutation, or streaming Agent response.
- These features cross HTTP, schema, service, repository, encryption,
  SQLAlchemy, Alembic, and background-task boundaries. A change is incomplete
  until those layers and their tests agree.

### 2. Signatures

Public and creator-owned Workshop operations:

```text
GET|PATCH /api/v1/users/me/workshop
GET       /api/v1/users/me/workshop/preview
POST      /api/v1/users/me/workshop/publish
POST      /api/v1/users/me/workshop/withdraw
POST|PATCH|DELETE /api/v1/users/me/workshop/social-accounts[/{account_id}]
POST|PATCH|DELETE /api/v1/users/me/workshop/contacts[/{contact_id}]
PUT|DELETE        /api/v1/users/me/workshop/projects/{project_id}
GET|PUT|DELETE    /api/v1/users/me/workshop/brand-authorizations[/{brand_id}]
GET       /api/v1/workshops/{creator_id}
```

Brand and engagement operations:

```text
POST|GET          /api/v1/brands
GET|PATCH         /api/v1/brands/{brand_id}
GET|PATCH|DELETE  /api/v1/brands/{brand_id}/members[/{user_id}]
POST|DELETE       /api/v1/brands/{brand_id}/invitations[/{invitation_id}]
GET               /api/v1/users/me/brand-invitations
POST              /api/v1/users/me/brand-invitations/{invitation_id}/accept
POST              /api/v1/users/me/brand-invitations/{invitation_id}/decline
GET               /api/v1/brands/{brand_id}/creator-discovery
GET|PUT|DELETE    /api/v1/brands/{brand_id}/follows[/{creator_id}]
GET|POST|PATCH    /api/v1/brands/{brand_id}/interests[/{interest_id}]
GET|PATCH|POST    /api/v1/users/me/brand-inbox[/{item_id}|/mark-read]
PATCH             /api/v1/users/me/brand-interests/{interest_id}
```

Agent streaming:

```text
POST /api/v1/conversations/{conversation_id}/messages/stream
Content-Type: text/event-stream
```

Persistence owners:

```text
brand.py       -> organizations, memberships, invitations
workshop.py    -> drafts, immutable publications, child snapshots,
                  authorizations, follows, interests, inbox
idempotency.py -> idempotency records and durable Agent stream runs
```

### 3. Contracts

Workshop field visibility is exactly:

```text
private | workshop_public | brands_only | authorized_brands
```

- `private` is visible only in the creator-owned draft response.
- `workshop_public` is visible anonymously.
- `brands_only` requires an active membership in the selected brand.
- `authorized_brands` requires both active brand membership and an active
  creator-to-brand authorization.
- Contacts accept only `private` or `authorized_brands`. The persisted value
  and the copied publication value are encrypted. Public projection must omit
  unauthorized contact rows entirely.
- Social accounts and selected projects are independent child resources with
  their own visibility and sort order.
- `publish` copies the current draft and child rows into a new immutable
  publication snapshot. Editing a draft or source project must not mutate an
  already-published snapshot. `withdraw` removes the public entry point but
  retains the draft, authorization, and engagement history.
- Publication versions are unique per creator. `published_at` records the
  publication action; snapshot `updated_at` records the draft revision copied
  by that action, so discovery can honor both declared sort fields without
  consulting later private draft edits.

Brand roles are exactly `owner | member`. Every active member may use
discovery, follows, and interests. Only owners may edit the organization,
invite users, or change membership. A brand must always retain an owner.
Creator authorization is organization-wide and therefore applies to every
active member of that brand. Accepting an interest never grants authorization.

One active follow row exists per brand and creator and moves between
`active/inactive`. One pending interest may exist per brand and creator;
terminal states are `accepted`, `declined`, and `withdrawn`. Follow and
interest changes create or update creator inbox rows and unread state.

Every Bearer-authenticated `POST`, `PUT`, `PATCH`, and `DELETE`, including
logout, requires `Idempotency-Key`. Registration and login are unauthenticated
and therefore outside this contract. The key is 8 through 128 ASCII
characters. Scope is authenticated user, HTTP method, normalized concrete
request path, and key digest. Brand IDs are naturally part of concrete brand
paths and are not a separate scope dimension. The request fingerprint includes
method, normalized path, canonical query pairs, and body. JSON bodies are
parsed and deterministically serialized; multipart bodies use normalized form
fields plus file byte digests and never include the random boundary. Completed
responses are encrypted and replay with `Idempotency-Replayed: true`.

Ordinary responses remain replayable for at least 24 hours. Commercial task
authorization and settlement records remain until at least 24 hours after the
task deadline. The deployed table still names the concrete-path column
`route_template` and retains nullable `brand_id` for migration compatibility;
new records always store `brand_id = NULL`.

SSE event names are:

```text
turn.started
response.delta
tool.started
tool.completed
turn.completed
turn.failed
```

Tool events expose only the tool name and status. They never expose arguments,
raw tool results, credentials, or exception text. The background Agent turn
uses its own database session and survives client disconnect. A completed
idempotent replay emits only the cached `turn.started` and terminal event.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Anonymous request reads public field | Include the field |
| Anonymous request reads non-public field | Return `null` or omit the child row |
| Brand member reads `brands_only` | Include the field |
| Non-member supplies a brand UUID | Do not reveal brand data |
| Authorized field without active authorization | Omit it |
| Contact is malformed | `422 invalid_workshop_contact` |
| Workshop is absent, withdrawn, or never published | `404 workshop_not_published` |
| Foreign child Workshop item | `404 workshop_item_not_found` |
| Brand is absent or caller is not a member | `404 brand_not_found` |
| Member performs owner-only action | `403 brand_owner_required` |
| Mutation removes the last owner | `409 brand_last_owner_required` |
| Invitation or interest is no longer pending | `409 *_state_conflict` |
| Authenticated business write has no valid key | `400 idempotency_key_required` |
| Same key and same fingerprint is complete | Replay status, safe headers, and body |
| Same key has a different fingerprint | `409 idempotency_key_reused` |
| Same idempotent operation is still running | `409 idempotency_request_in_progress` with `error.retryable=true` |
| Processing record exceeds the Agent run-lock TTL | Mark a related turn failed, release its stale lock, and return `409 idempotency_outcome_unknown` |
| SSE client disconnects | Continue the turn and persist its terminal result |

### 5. Good / Base / Bad Cases

- Good: discovery filtering is performed in SQL against only fields visible to
  the requesting brand, then the same centralized projector builds responses.
- Base: a creator edits a draft, publishes it, edits the source project, and
  anonymous readers still see the original project snapshot.
- Bad: filter all publications using private plaintext and remove hidden fields
  only after pagination; this leaks private data through hits and counts.
- Bad: decrypt a contact before membership and authorization checks.
- Bad: cancel the Agent task because the browser closed its SSE connection.

### 6. Tests Required

- Migration: upgrade a fresh SQLite file; assert all 17 tables, foreign keys,
  check constraints, partial unique indexes, and complete downgrade.
- Workshop: cover owner draft, public/brand/authorized projections,
  publication immutability, withdrawal, child CRUD, contact encryption, and
  project snapshot independence.
- Brand: cover owner/member permissions, cross-brand 404 behavior, invitation
  state transitions, and last-owner protection.
- Discovery: assert hidden values cannot affect query matches, filters,
  counts, or pagination; cover every filter and deterministic ordering.
- Engagement: cover follow/unfollow/refollow, one pending interest under
  concurrency, creator transitions, no implicit authorization, inbox
  filtering, and read state.
- Idempotency: assert missing key including logout, canonical JSON replay,
  concrete-path scope, reused-key rejection, retryable in-progress response,
  empty-204 replay, multipart fingerprinting, commercial concurrent
  deduplication, retention, and OpenAPI declaration for every authenticated
  mutation.
- Streaming: assert ordered deltas, sanitized tool events, persisted complete
  messages, replay without deltas, and background completion after disconnect.

### 7. Wrong vs Correct

#### Wrong

```python
publication.bio = draft.bio
db.commit()

items = list_all_publications(db)
items = [item for item in items if query in decrypt_every_field(item)]
```

This mutates the published resource in place and allows hidden data to affect
discovery results.

#### Correct

```python
publication = clone_publication_snapshot(draft)
db.add(publication)

rows = discover_visible_publications(
    db,
    brand_id=brand_id,
    query=query,
    limit=limit,
    offset=offset,
)
return [project_publication(row, audience=audience) for row in rows]
```

Publishing creates a new snapshot, SQL applies visibility-aware discovery, and
the projector remains the final disclosure boundary.

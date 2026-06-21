# Documentation for `athena/api/routers/saved.py`

## Overview
Athena — Saved Lists Router

User-created lists (e.g. "NLP", "Computer Vision") for organising content items.

GET    /api/v1/lists                       — all lists (pass `item_id` to also get `contains_item`)
POST   /api/v1/lists                       — create a list
PATCH  /api/v1/lists/{id}                   — rename a list
DELETE /api/v1/lists/{id}                   — delete a list
GET    /api/v1/lists/{id}/items             — items in a list, as feed cards
POST   /api/v1/lists/{id}/items             — add an item to a list (`{item_id}`)
DELETE /api/v1/lists/{id}/items/{item_id}   — remove an item from a list

## Functions
### `_parse_uuid`
Validate a path/body UUID, raising 400 on a malformed value.

### `_get_list_or_404`
Fetch a `SavedList` by id or raise 404.

### `list_lists`
Return all lists with their item counts. When `item_id` is supplied, each list
also carries `contains_item` so the add-to-list menu can show current membership.

### `create_list`
Create a new list (201).

### `rename_list`
Rename a list.

### `delete_list`
Delete a list and its memberships (204).

### `get_list_items`
Return the content items saved in a list, serialised as feed cards.

### `add_item_to_list`
Add a content item to a list (idempotent; 201).

### `remove_item_from_list`
Remove a content item from a list (204).

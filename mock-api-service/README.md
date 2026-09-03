# Reliable Data Pipeline — Mock API Service

This service provides the three upstream HTTP APIs used by the take-home challenge.

## Start with Docker

```bash
docker compose up --build
```

The service listens at:

```text
http://localhost:8080
```

Check readiness:

```bash
curl http://localhost:8080/health
```

Reset deterministic state:

```bash
curl -X POST http://localhost:8080/admin/reset
```

## Start without Docker

Requires Python 3.11+ and no third-party packages.

```bash
python server.py --port 8080
```

## API Contract

### Source A

```http
GET /source-a/products?page=1
```

Characteristics:

- page-number pagination
- 2 products per page
- 3 pages in the supplied fixture
- fixed moderate latency
- stable schema

Example:

```json
{
  "page": 1,
  "total_pages": 3,
  "products": [
    {
      "id": "a-101",
      "name": "Mechanical Keyboard",
      "price": 89.99,
      "category": "electronics"
    }
  ]
}
```

### Source B

First page:

```http
GET /source-b/products
```

Following pages use the returned opaque cursor:

```http
GET /source-b/products?cursor=cursor-2
```

Characteristics in the default `standard` scenario:

- cursor pagination
- 2 records per page
- different field names from Source A
- price represented as integer cents
- one intentionally malformed price in the fixture
- `cursor-2` fails once with HTTP 503 before succeeding
- `cursor-3` fails twice with HTTP 502 before succeeding
- transient responses include `Retry-After`
- reset restores the failure sequence

Example successful response:

```json
{
  "items": [
    {
      "sku": "b-201",
      "title": "Desk Lamp",
      "amount_cents": 3499,
      "department": "home"
    }
  ],
  "next_cursor": "cursor-2"
}
```

### Source C

```http
GET /source-c/products?offset=0&limit=2
```

Characteristics:

- offset/limit pagination
- maximum page size: 2
- price represented as a string
- maximum 2 requests in a rolling 1-second window
- requests exceeding the limit return HTTP 429
- rate-limit responses include `Retry-After`
- successful responses include `X-RateLimit-Limit` and `X-RateLimit-Window`

Example:

```json
{
  "data": [
    {
      "product_id": "c-301",
      "product_name": "USB-C Hub",
      "price": "49.50",
      "type": "electronics"
    }
  ],
  "next_offset": 2,
  "max_page_size": 2
}
```

## Determinism

The default behavior is deterministic. `POST /admin/reset` restores Source B's transient-failure counters and clears Source C's rate-limit window.

Restarting the process or container also resets state.

## Tests

No third-party test framework is required:

```bash
python -m unittest -v test_server.py
```

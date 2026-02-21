---
name: api-design
description: Design clean REST and GraphQL APIs — endpoints, schemas, versioning, error handling.
always: false
task_types: [coding, documentation]
---

# API Design

## REST Best Practices

### Resource Naming
- Use nouns, not verbs: `/users`, `/orders`, `/products` (not `/getUsers`).
- Use plural names for collections: `/users` not `/user`.
- Nest for relationships: `/users/{id}/orders` for orders belonging to a user.
- Use kebab-case for multi-word resources: `/order-items`.
- Keep URLs shallow; avoid nesting more than two levels deep.

### HTTP Methods
| Method | Purpose | Idempotent | Safe |
|--------|---------|------------|------|
| GET | Retrieve resource(s) | Yes | Yes |
| POST | Create a new resource | No | No |
| PUT | Full replacement of a resource | Yes | No |
| PATCH | Partial update of a resource | No | No |
| DELETE | Remove a resource | Yes | No |

### Status Codes
- **200 OK**: Successful GET, PUT, PATCH, or DELETE.
- **201 Created**: Successful POST that created a resource. Include `Location` header.
- **204 No Content**: Successful DELETE or PUT with no response body.
- **400 Bad Request**: Malformed request syntax or invalid parameters.
- **401 Unauthorized**: Missing or invalid authentication credentials.
- **403 Forbidden**: Authenticated but lacking permission.
- **404 Not Found**: Resource does not exist.
- **409 Conflict**: Request conflicts with current state (e.g., duplicate).
- **422 Unprocessable Entity**: Valid syntax but semantic errors (validation failures).
- **429 Too Many Requests**: Rate limit exceeded. Include `Retry-After` header.
- **500 Internal Server Error**: Unhandled server failure.

### Pagination
- Use cursor-based pagination for large or frequently changing datasets: `?cursor=abc123&limit=25`.
- Use offset-based pagination for simpler cases: `?page=2&per_page=25`.
- Always return pagination metadata: `total_count`, `next_cursor` or `next_page`, `has_more`.

### Filtering and Sorting
- Filter via query parameters: `GET /orders?status=shipped&created_after=2025-01-01`.
- Sort with a `sort` parameter: `GET /users?sort=-created_at,name` (prefix `-` for descending).
- Support sparse fieldsets where practical: `GET /users?fields=id,name,email`.

## Versioning Strategies

- **URL path versioning** (recommended for simplicity): `/v1/users`, `/v2/users`.
- **Header versioning**: `Accept: application/vnd.myapi.v2+json`.
- **Query parameter**: `?version=2` (least common, harder to cache).
- Maintain at most two versions simultaneously. Deprecate old versions with clear timelines and `Sunset` headers.

## Authentication

- **API Keys**: Simple, suitable for server-to-server. Pass in `X-API-Key` header, never in URLs.
- **OAuth 2.0**: Use for third-party access. Implement authorization code flow for web apps, client credentials for service-to-service.
- **JWT (JSON Web Tokens)**: Stateless auth tokens. Keep payloads small, set short expiration, use refresh tokens for long sessions.
- Always use HTTPS. Never transmit credentials over plain HTTP.

## Error Response Format

Use a consistent error schema across all endpoints:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request body contains invalid fields.",
    "details": [
      {
        "field": "email",
        "message": "Must be a valid email address.",
        "value": "not-an-email"
      }
    ],
    "request_id": "req_abc123"
  }
}
```

Include a `request_id` for traceability. Use machine-readable error codes alongside human-readable messages.

## OpenAPI / Swagger Documentation

- Write an OpenAPI 3.x specification for every API. Keep it in `openapi.yaml` at the project root.
- Document all endpoints, request/response schemas, authentication methods, and error responses.
- Use `$ref` for reusable schemas to keep the spec DRY.
- Generate interactive docs with Swagger UI or Redoc.
- Validate the spec in CI with tools like `spectral` or `openapi-generator validate`.

## Rate Limiting

- Implement rate limiting to protect against abuse: per-user, per-API-key, or per-IP.
- Return rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
- Use 429 status code when limits are exceeded, with a `Retry-After` header.
- Consider tiered limits: stricter for anonymous, more generous for authenticated users.

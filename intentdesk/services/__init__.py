"""Service layer.

Every piece of real behaviour lives here. The REST API and the MCP server are
both thin adapters over these functions and must not hold business logic of
their own — that is what keeps the two front ends from drifting apart.
"""

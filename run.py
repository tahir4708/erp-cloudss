#!/usr/bin/env python3
"""Launch the XAU/USD signal bot web app."""

import os

import uvicorn


if __name__ == "__main__":
    # Hosts like Render/Railway inject the port via the PORT env var.
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)

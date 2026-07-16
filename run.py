#!/usr/bin/env python3
"""Launch the XAU/USD signal bot web app."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)

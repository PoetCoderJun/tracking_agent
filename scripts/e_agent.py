#!/usr/bin/env python3
from agent import e_agent as _impl

globals().update(
    {
        name: getattr(_impl, name)
        for name in dir(_impl)
        if not name.startswith("__")
    }
)


if __name__ == "__main__":
    raise SystemExit(main())

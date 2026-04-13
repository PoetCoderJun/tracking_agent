#!/usr/bin/env python3
from world.perception import cli as _impl

globals().update(
    {
        name: getattr(_impl, name)
        for name in dir(_impl)
        if not name.startswith("__")
    }
)


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the lightweight local demo flow."""

import json

from demo.cli.main import run_demo_flow


if __name__ == "__main__":
    print(json.dumps(run_demo_flow(), indent=2, default=str))

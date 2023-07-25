from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Dict, List, Optional
import json

import jsonschema

@dataclass
class Event:
    label: str

    def run(self):
        # Base `Event` doesn't do anything
        raise NotImplementedError

@dataclass
class ReactionCycle(Event):
    events: Iterable[Event]
    cleaving: Dict
    iterations: int = 1

@dataclass
class Group(Event):
    events: Iterable[Event]
    iterations: int = 1

@dataclass
class ImageSequence(Event):
    ImageSequence_args: Dict

@dataclass
class Wait(Event):
    duration_ms: int

SEQUENCING_PROTOCOL_SCHEMA_PATH = "sequencing_protocol_schema.json"
with open(SEQUENCING_PROTOCOL_SCHEMA_PATH) as schema_file:
    SEQUENCING_PROTOCOL_SCHEMA_JSON = json.load(schema_file)

def validate_protocol_json(protocol_json: Dict) -> None:
    jsonschema.validate(protocol_json, SEQUENCING_PROTOCOL_SCHEMA_JSON)

def load_protocol_json(protocol_json: Dict) -> Event:
    # Assumes that `protocol_json` is valid. Make sure to call `validate_protocol_json` first.
    # Can't do this validation here because of the recursion.
    label = protocol_json["label"]
    event_type = protocol_json["event_type"]

    if event_type == "ReactionCycle":
        args = protocol_json["ReactionCycle_args"]
        return ReactionCycle(
            label,
            # Conversion to `list` needed so that we can iterate through this more than once
            list(map(load_protocol_json, args["events"])),
            args["cleaving"],
            args["iterations"])
    elif event_type == "Group":
        args = protocol_json["Group_args"]
        return Group(
            label,
            # Conversion to `list` needed so that we can iterate through this more than once
            list(map(load_protocol_json, args["events"])),
            args["iterations"])
    elif event_type == "ImageSequence":
        return ImageSequence(label, protocol_json["ImageSequence_args"])
    elif event_type == "Wait":
        return Wait(label, protocol_json["Wait_args"]["duration_ms"])
    else:
        raise ValueError(f"Unsupported type {event_type}")

parser = ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--hal", help="Path to HAL domain socket")
group.add_argument("--mock", action="store_true")
parser.add_argument("protocol", help="Path to the protocol file to run")

if __name__ == "__main__":
    args = parser.parse_args()

    # Connect to the HAL
    # TODO

    # Load the protocol
    with open(args.protocol) as protocol_file:
        protocol_json = json.load(protocol_file)
    validate_protocol_json(protocol_json)
    protocol = load_protocol_json(protocol_json)

    protocol.run()

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import json
import time

import jsonschema

@dataclass
class RunContextNode:
    event: Event
    step_index: Optional[int] = None
    iteration: Optional[int] = None

    def __str__(self) -> str:
        output = f"{type(self.event).__name__}"
        if self.iteration is not None:
            output += f"-iteration_{self.iteration}"
        if self.step_index is not None:
            output += f"-step_{self.step_index}"
        return output

@dataclass
class RunContext:
    path: List[RunContextNode]
    root_dir: Path
    mock: bool = False

    def create_child_context(self, event: Event, step_index: Optional[int] = None, iteration: Optional[int] = None) -> RunContext:
        child_node = RunContextNode(event)
        child_context = RunContext(self.path.copy(), self.root_dir, self.mock)

        last_node = child_context.path[-1]
        if step_index is not None:
            last_node.step_index = step_index
        if iteration is not None:
            last_node.iteration = iteration
        
        child_context.path.append(child_node)
        return child_context
    
    def __str__(self) -> str:
        return "/".join(map(str, self.path))
    
    def output_dir(self) -> Path:
        # TODO: Define directory structure -- might not want everything in its own directory
        # TODO: Ensure this is available
        return self.root_dir / str(self)

@dataclass
class Event:
    label: str

    def run(self, context: RunContext):
        # TODO: Use a logging library
        print(f">>> Running {type(self).__name__} step")
        print(f"Path: {context}\nLabel: {self.label}")
        print(f"Time: {time.asctime(time.localtime(time.time()))}\n")

@dataclass
class ReactionCycle(Event):
    events: List[Event]
    cleaving: Dict
    iterations: int = 1

    def run(self, context: RunContext):
        super().run(context)
        for iteration in range(self.iterations):
            for step_index, event in enumerate(self.events):
                event.run(context.create_child_context(event, step_index, iteration))

            # TODO: Talk to the HAL to do the cleaving
            pass

@dataclass
class Group(Event):
    events: List[Event]
    iterations: int = 1

    def run(self, context: RunContext):
        super().run(context)
        for iteration in range(self.iterations):
            for step_index, event in enumerate(self.events):
                event.run(context.create_child_context(event, step_index, iteration))

@dataclass
class ImageSequence(Event):
    ImageSequence_args: Dict

    def run(self, context: RunContext):
        super().run(context)
        # TODO: Talk to the HAL to capture the image sequence
        pass

@dataclass
class Wait(Event):
    duration_ms: int

    def run(self, context: RunContext):
        super().run(context)
        if not context.mock:
            print(f"Waiting {self.duration_ms} ms\n")
            time.sleep(self.duration_ms / 1000)
        else:
            print(f"{self.duration_ms} ms wait skipped -- `mock = True`\n")

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
parser.add_argument("output_directory", help="Where to save output files")

if __name__ == "__main__":
    args = parser.parse_args()

    # Load the protocol
    with open(args.protocol) as protocol_file:
        protocol_json = json.load(protocol_file)
    validate_protocol_json(protocol_json)
    protocol = load_protocol_json(protocol_json)

    # Connect to the HAL
    # TODO

    protocol.run(RunContext([RunContextNode(protocol)], Path(args.output_directory), args.mock))

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import time

import jsonschema

from hal import Hal

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
    hal: Optional[Hal]

    def create_child_context(self, event: Event, step_index: Optional[int] = None, iteration: Optional[int] = None) -> RunContext:
        child_node = RunContextNode(event)
        child_context = RunContext(self.path.copy(), self.root_dir, self.hal)

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
        return self.root_dir / str(self)

@dataclass
class Event:
    label: str
    protocol_line: int

    def run(self, context: RunContext):
        # TODO: Use a logging library
        print(f">>> Running {type(self).__name__} step")
        print(f"Line {self.protocol_line}, path: {context}\nLabel: {self.label}")
        print(f"Time: {time.asctime(time.localtime(time.time()))}\n")

        # TODO: Emit this context from the root Event so the viewer knows where we are

    def __len__(self):
        return 1

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

            if not context.hal:
                print("Cleaving skipped -- `mock = True`\n")
            else:
                # TODO: This should be its own Event so it shows up in the GUI
                # This Event shouldn't be exposed in the protocol specification
                # Make sure to account for this in the length below and the viewer
                output_dir = context.output_dir()
                output_dir.mkdir(parents=True)
                context.hal.run_command({
                    "command": "cleave",
                    "args": {
                        "cleave_args": self.cleaving,
                        "output_dir": str(output_dir)
                    }
                })

    def __len__(self):
        return sum(map(len, self.events)) + 1

@dataclass
class Group(Event):
    events: List[Event]
    iterations: int = 1

    def run(self, context: RunContext):
        super().run(context)
        for iteration in range(self.iterations):
            for step_index, event in enumerate(self.events):
                event.run(context.create_child_context(event, step_index, iteration))

    def __len__(self):
        return sum(map(len, self.events)) + 1

@dataclass
class ImageSequence(Event):
    imaging_args: Dict

    def run(self, context: RunContext):
        super().run(context)

        if not context.hal:
            print("Imaging skipped -- `mock = True`\n")
        else:
            output_dir = context.output_dir()
            output_dir.mkdir(parents=True)
            context.hal.run_command({
                "command": "run_image_sequence",
                "args": {
                    "sequence": {
                        "label": self.label,
                        **self.imaging_args
                    },
                    "output_dir": str(output_dir)
                }
            })

@dataclass
class Wait(Event):
    duration_ms: int

    def run(self, context: RunContext):
        super().run(context)
        print(f"Waiting {self.duration_ms} ms")

        if not context.hal:
            print(f"Wait skipped -- `mock = True`\n")
            return

        time.sleep(self.duration_ms / 1000)
        print()

SEQUENCING_PROTOCOL_SCHEMA_PATH = "sequencing_protocol_schema.json"
with open(SEQUENCING_PROTOCOL_SCHEMA_PATH) as schema_file:
    SEQUENCING_PROTOCOL_SCHEMA_JSON = json.load(schema_file)

def validate_protocol_json(protocol_json: Dict) -> None:
    jsonschema.validate(protocol_json, SEQUENCING_PROTOCOL_SCHEMA_JSON)

def load_protocol_json(protocol_line: int, protocol_json: Dict) -> Tuple[Event, int]:
    # Assumes that `protocol_json` is valid. Make sure to call `validate_protocol_json` first.
    # Can't do this validation here because of the recursion.
    label = protocol_json["label"]
    event_type = protocol_json["event_type"]

    if event_type == "ReactionCycle":
        args = protocol_json["ReactionCycle_args"]

        # Create the children, making sure to give them the correct line numbers.
        next_protocol_line = protocol_line + 1
        children = []
        event_len = 1
        for event_json in args["events"]:
            child, child_len = load_protocol_json(next_protocol_line, event_json)
            next_protocol_line += child_len
            event_len += child_len
            children.append(child)

        return ReactionCycle(
            label,
            protocol_line,
            children,
            args["cleaving"],
            args["iterations"]), event_len

    elif event_type == "Group":
        args = protocol_json["Group_args"]

        # Create the children, making sure to give them the correct line numbers.
        next_protocol_line = protocol_line + 1
        children = []
        event_len = 1
        for event_json in args["events"]:
            child, child_len = load_protocol_json(next_protocol_line, event_json)
            next_protocol_line += child_len
            event_len += child_len
            children.append(child)

        return Group(
            label,
            protocol_line,
            children,
            args["iterations"]), event_len

    elif event_type == "ImageSequence":
        return ImageSequence(label, protocol_line, protocol_json["ImageSequence_args"]), 1

    elif event_type == "Wait":
        return Wait(label, protocol_line, protocol_json["Wait_args"]["duration_ms"]), 1

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
    protocol, _ = load_protocol_json(0, protocol_json)

    # Connect to the HAL
    if not args.mock:
        hal = Hal(args.hal)
    else:
        hal = None

    protocol.run(RunContext([RunContextNode(protocol)], Path(args.output_directory), hal))

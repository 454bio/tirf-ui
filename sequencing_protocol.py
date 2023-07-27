from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar, Dict, List, Optional, Tuple
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
    readable_type: ClassVar[str] = "Abstract Event"
    label: str
    protocol_line: int
    protocol_depth: int

    def __post_init__(self):
        # Event that is emitted when we start a new step.
        # Initialized here to avoid exposing this in the constructor.
        self.event_run_callback: Optional[Callable[[RunContext], None]] = None

    def run(self, context: RunContext):
        # TODO: Use a logging library
        print(f">>> Running {type(self).__name__} step")
        print(f"Line {self.protocol_line}, depth {self.protocol_depth}, path: {context}\nLabel: {self.label}")
        print(f"Time: {time.asctime(time.localtime(time.time()))}\n")

        # Notify the listener that we're running a new Event
        # The listener is only registered on the root Event
        callback = context.path[0].event.event_run_callback
        if callback is not None:
            callback(context)

        if not context.hal:
            # Delay so we can actually see what's going on in a mock run
            time.sleep(1)

    def __len__(self):
        return 1
    
    def __iter__(self):
        yield self
    
    def gui_details(self, context: Optional[RunContext] = None) -> Optional[str]:
        return None

@dataclass
class ReactionCycle(Event):
    readable_type: ClassVar[str] = "Reaction Cycle"
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
                # Make sure to account for this in the __len__ and __iter__ below and the viewer
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
    
    def __iter__(self):
        yield self
        for event in self.events:
            for node in event:
                yield node
    
    def gui_details(self, context: Optional[RunContext] = None) -> str:
        # TODO: Use the context to print the current iteration
        return f"{self.iterations} iterations, {len(self) - 1} children:"

@dataclass
class Group(Event):
    readable_type: ClassVar[str] = "Group"
    events: List[Event]
    iterations: int = 1

    def run(self, context: RunContext):
        super().run(context)
        for iteration in range(self.iterations):
            for step_index, event in enumerate(self.events):
                event.run(context.create_child_context(event, step_index, iteration))

    def __len__(self):
        return sum(map(len, self.events)) + 1
    
    def __iter__(self):
        yield self
        for event in self.events:
            for node in event:
                yield node
    
    def gui_details(self, context: Optional[RunContext] = None) -> str:
        # TODO: Use the context to print the current iteration
        return f"{self.iterations} iterations, {len(self) - 1} children:"

@dataclass
class ImageSequence(Event):
    readable_type: ClassVar[str] = "Image Sequence"
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
    
    def gui_details(self, context: Optional[RunContext] = None) -> Optional[str]:
        # TODO: Parse out more details
        images = self.imaging_args["images"]
        return f"{len(images)} images"

@dataclass
class Wait(Event):
    readable_type: ClassVar[str] = "Wait"
    duration_ms: int

    def run(self, context: RunContext):
        super().run(context)
        print(f"Waiting {self.duration_ms} ms")

        if not context.hal:
            print(f"Wait skipped -- `mock = True`\n")
            return

        time.sleep(self.duration_ms / 1000)
        print()

    def gui_details(self, context: Optional[RunContext] = None) -> Optional[str]:
        return f"{self.duration_ms / 1000} seconds"

SEQUENCING_PROTOCOL_SCHEMA_PATH = "sequencing_protocol_schema.json"
with open(SEQUENCING_PROTOCOL_SCHEMA_PATH) as schema_file:
    SEQUENCING_PROTOCOL_SCHEMA_JSON = json.load(schema_file)

def validate_protocol_json(protocol_json: Dict) -> None:
    jsonschema.validate(protocol_json, SEQUENCING_PROTOCOL_SCHEMA_JSON)

def load_protocol_json(protocol_json: Dict, protocol_line: int = 0, depth: int = 0) -> Tuple[Event, int]:
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
            child, child_len = load_protocol_json(event_json, next_protocol_line, depth+1)
            next_protocol_line += child_len
            event_len += child_len
            children.append(child)

        return ReactionCycle(
            label,
            protocol_line,
            depth,
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
            child, child_len = load_protocol_json(event_json, next_protocol_line, depth+1)
            next_protocol_line += child_len
            event_len += child_len
            children.append(child)

        return Group(
            label,
            protocol_line,
            depth,
            children,
            args["iterations"]), event_len

    elif event_type == "ImageSequence":
        return ImageSequence(label, protocol_line, depth, protocol_json["ImageSequence_args"]), 1

    elif event_type == "Wait":
        return Wait(label, protocol_line, depth, protocol_json["Wait_args"]["duration_ms"]), 1

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
    protocol, _ = load_protocol_json(protocol_json)

    # Connect to the HAL
    if not args.mock:
        hal = Hal(args.hal)
    else:
        hal = None

    protocol.run(RunContext([RunContextNode(protocol)], Path(args.output_directory), hal))

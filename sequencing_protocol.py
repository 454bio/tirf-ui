from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar, Dict, List, Optional, Tuple
import json
import time

import jsonschema
from PySide2.QtCore import QThread

from hal import IHal, Hal, MockHal

@dataclass
class RunContextNode:
    event: Event
    step_index: Optional[int] = None
    iteration: Optional[int] = None

    def __post_init__(self):
        self.start_time = time.time()

    def __str__(self) -> str:
        output = self.event.short_type
        if self.iteration is not None:
            output += f"i{self.iteration}"
        if self.step_index is not None:
            output += f"s{self.step_index}"
        return output

@dataclass
class RunState:
    sequence_number: int = 0
    cycle_number: int = 0

    def get_next_sequence_number(self, reserve=1) -> int:
        sequence_number = self.sequence_number
        self.sequence_number += reserve
        return sequence_number

@dataclass
class RunContext:
    path: List[RunContextNode]
    root_dir: Path
    hal: IHal
    state: RunState
    thread: Optional[QThread] = None

    def create_child_context(self, event: Event, step_index: Optional[int] = None, iteration: Optional[int] = None) -> RunContext:
        child_node = RunContextNode(event)
        child_context = RunContext(self.path.copy(), self.root_dir, self.hal, self.state, self.thread)

        last_node = child_context.path[-1]
        if step_index is not None:
            last_node.step_index = step_index
        if iteration is not None:
            last_node.iteration = iteration
        
        child_context.path.append(child_node)
        return child_context
    
    def __str__(self) -> str:
        return "-".join(map(str, self.path))

    def output_dir(self) -> Path:
        return self.root_dir

@dataclass
class Event:
    readable_type: ClassVar[str] = "Abstract Event"
    short_type: ClassVar[str] = "E"
    label: str
    protocol_line: int
    protocol_depth: int

    def __post_init__(self):
        # Event that is emitted when we start a new step.
        # Initialized here to avoid exposing this in the constructor.
        self.event_run_callback: Optional[Callable[[RunContext], None]] = None

    def run(self, context: RunContext):
        thread = context.thread
        if thread is not None and thread.isInterruptionRequested():
            raise InterruptedError

        # TODO: Use a logging library
        print(f">>> Running {type(self).__name__} step")
        print(f"Line {self.protocol_line}, depth {self.protocol_depth}, path: {context}\nLabel: {self.label}")
        print(f"Protocol path: {context}")
        print(f"Time: {time.asctime(time.localtime(time.time()))}")

        # Notify the listener that we're running a new Event
        # The listener is only registered on the root Event
        callback = context.path[0].event.event_run_callback
        if callback is not None:
            callback(context)

    def __len__(self):
        return 1
    
    def __iter__(self):
        yield self
    
    def gui_details(self, context: Optional[RunContext] = None) -> Optional[str]:
        return None

@dataclass
class ReactionCycle(Event):
    readable_type: ClassVar[str] = "Reaction Cycle"
    short_type: ClassVar[str] = "R"
    events: List[Event]
    cleaving: Dict
    iterations: int = 1

    def run(self, context: RunContext):
        super().run(context)
        for iteration in range(self.iterations):
            for step_index, event in enumerate(self.events):
                event.run(context.create_child_context(event, step_index, iteration))

            # Cleaving step
            # TODO: This is doing all of the work from Event.run(). Should this just be a dynamically generated Event instead?
            context.path[-1].step_index = None
            callback = context.path[0].event.event_run_callback
            if callback is not None:
                callback(context)

            # Cleaving can create more than one image, but this will not be reflected in the sequence number.
            # The HAL will populate $imageIndex and $timestamp appropriately.
            label = "365"  # UV wavelength
            context.hal.run_command({
                "command": "cleave",
                "args": {
                    "cleave_args": {
                        **self.cleaving,
                        "filename": f"{context.state.get_next_sequence_number():06}_$imageIndex_{label}_C{context.state.cycle_number:04}_$timestamp_P-{context}-C.tif"
                    },
                    "output_dir": str(context.output_dir())
                }
            }, context.thread)

            context.state.cycle_number += 1

    def __len__(self):
        return sum(map(len, self.events)) + 1
    
    def __iter__(self):
        yield self
        for event in self.events:
            for node in event:
                yield node
    
    def gui_details(self, context: Optional[RunContext] = None) -> str:
        cleave_duration_s = self.cleaving["cleaving_duration_ms"] / 1000
        if context is None:
            return f"{self.iterations} iterations, {len(self) - 1} children, then cleave for {cleave_duration_s} seconds:"

        # Find the corresponding node so we can display which iteration we're on.
        # Yes, this is O(n) in the length of the path.
        # While it is technically valid to have a long path, if your protocol is more than 5 levels deep you have other problems.
        my_node: Optional[RunContextNode] = None
        for node in context.path:
            if self == node.event:
                my_node = node
                break

        if my_node is None or my_node.iteration is None:
            raise ValueError

        if my_node.step_index is None:
            # Running the cleaving step
            return f"Cleaving for {cleave_duration_s} seconds in iteration {my_node.iteration+1} of {self.iterations}, {len(self) - 1} children:"
        else:
            return f"Running iteration {my_node.iteration+1} of {self.iterations}, {len(self) - 1} children, then cleave for {cleave_duration_s} seconds:"

@dataclass
class Group(Event):
    readable_type: ClassVar[str] = "Group"
    short_type: ClassVar[str] = "G"
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
        if context is None:
            return f"{self.iterations} iterations, {len(self) - 1} children:"

        # Find the corresponding node so we can display which iteration we're on.
        # Yes, this is O(n) in the length of the path.
        # While it is technically valid to have a long path, if your protocol is more than 5 levels deep you have other problems.
        my_node: Optional[RunContextNode] = None
        for node in context.path:
            if self == node.event:
                my_node = node
                break

        if my_node is None or my_node.iteration is None or my_node.step_index is None:
            raise ValueError

        return f"Running iteration {my_node.iteration+1} of {self.iterations}, {len(self) - 1} children:"

@dataclass
class ImageSequence(Event):
    readable_type: ClassVar[str] = "Image Sequence"
    short_type: ClassVar[str] = "I"
    imaging_args: Dict

    def run(self, context: RunContext):
        super().run(context)

        imaging_args = self.imaging_args.copy()
        for image in imaging_args["images"]:
            # The label is used as the wavelength.
            image["filename"] = f"{context.state.get_next_sequence_number():06}_$imageIndex_$imageLabel_C{context.state.cycle_number:04}_$timestamp_P-{context}.tif"
        context.hal.run_command({
            "command": "run_image_sequence",
            "args": {
                "sequence": {
                    "label": self.label,
                    **imaging_args
                },
                "output_dir": str(context.output_dir())
            }
        }, context.thread)

    def gui_details(self, context: Optional[RunContext] = None) -> Optional[str]:
        # TODO: Parse out more details
        images = self.imaging_args["images"]
        return f"{len(images)} images"

# TODO: Calculate a sane value for this using the temperature difference
MAX_TEMPERATURE_WAIT_S = 10 * 60  # 10 minutes
# TODO: Calculate a sane value for this using the estimated time remaining in the protocol
MAX_TEMPERATURE_HOLD_S = 8 * 60 * 60  # 8 hours

@dataclass
class SetTemperature(Event):
    readable_type: ClassVar[str] = "Set Temperature"
    short_type: ClassVar[str] = "T"
    set_temperature_args: Dict

    def run(self, context: RunContext):
        super().run(context)

        context.hal.run_command({
            "command": "wait_for_temperature",
            "args": {
                "temperature_args": {
                    "target_temperature_kelvin": self.set_temperature_args["temperature_kelvin"],
                    "wait_time_s": MAX_TEMPERATURE_WAIT_S,
                    "hold_time_s": MAX_TEMPERATURE_HOLD_S
                }
            }
        }, context.thread)

    def gui_details(self, context: Optional[RunContext] = None) -> str:
        return f"Wait until {self.set_temperature_args['temperature_kelvin'] - 273.15} ºC"

@dataclass
class Wait(Event):
    readable_type: ClassVar[str] = "Wait"
    short_type: ClassVar[str] = "W"
    duration_ms: int

    def run(self, context: RunContext):
        super().run(context)
        print(f"Waiting {self.duration_ms} ms")

        # If we're in a QThread, periodically check if we need to stop
        # TODO: There's probably a better way to do this
        thread = context.thread
        if thread is not None:
            remaining_duration = self.duration_ms
            while remaining_duration > 0:
                duration = min(remaining_duration, 1000)
                thread.msleep(duration)
                remaining_duration -= duration
                if thread.isInterruptionRequested():
                    raise InterruptedError
        else:
            time.sleep(self.duration_ms / 1000)

    def gui_details(self, context: Optional[RunContext] = None) -> Optional[str]:
        mins, msecs = divmod(self.duration_ms, 60000)
        mins_str = f"{mins} minutes" if mins else ""
        secs_str = f"{msecs / 1000} seconds" if msecs else ""
        return " ".join(filter(bool, [mins_str, secs_str]))

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

    elif event_type == "SetTemperature":
        return SetTemperature(
            label,
            protocol_line,
            depth,
            protocol_json["SetTemperature_args"]), 1

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
        hal = Hal(args.hal, 45400)
    else:
        hal = MockHal()

    try:
        protocol.run(RunContext([RunContextNode(protocol)], Path(args.output_directory), hal, RunState()))
    except Exception as e:
        print(e)
    finally:
        hal.disable_heater(None)

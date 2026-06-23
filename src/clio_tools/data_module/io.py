"""Utility functions for module input / output standardisation."""

import re
from pathlib import Path
from textwrap import dedent
from typing import Self  # type: ignore

import networkx as nx
import yaml
from pydantic import BaseModel, Field, model_validator

SEMVER_REGEX = (
    r"^v?"
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>"
    r"(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*"
    r"))?"
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+"
    r"(?:\.[0-9a-zA-Z-]+)*))?$"
)

def _find_between(text: str, brackets: str) -> list[str]:
    """Helper to find text inside different bracket configurations."""
    pattern = rf"{re.escape(brackets[0])}(.*?){re.escape(brackets[1])}"
    return re.findall(pattern, text)


class Pathvar(BaseModel):
    """Schema for snakemake pathvar definition."""

    model_config = {"extra": "forbid"}

    default: str
    "Default setting of this pathvar."
    description: str
    "Brief explanation of the pathvar's purpose."


class Pathvars(BaseModel):
    """Schema for snakemake pathvar definition."""

    model_config = {"extra": "forbid"}

    snakemake_defaults: dict[str, Pathvar] = Field(default_factory=dict)
    "Snakemake default pathvars (logs, resources, results)."
    user_resources: dict[str, Pathvar] = Field(default_factory=dict)
    "User input resource pathvar."
    results: dict[str, Pathvar] = Field(default_factory=dict)
    "Module result pathvar."

    @model_validator(mode="after")
    def check_snakemake_defaults(self) -> Self:
        """Snakemake defaults are communicated correctly."""
        expected_defaults = {"logs", "resources", "results", "benchmarks"}
        mismatches = set(self.snakemake_defaults.keys()) - expected_defaults
        if mismatches:
            raise ValueError(
                f"{mismatches} does not match expected snakemake defaults {expected_defaults!r}"
            )
        for name, settings in self.snakemake_defaults.items():
            default = settings.default
            value = _find_between(default, "<>")
            if len(value) != 1 and value[0] != name:
                raise ValueError(
                    f"{name!r} default path must match snakemake default name."
                )
        return self

    @model_validator(mode="after")
    def check_user_resources(self) -> Self:
        """Ensure user resource pathvars follow a standard prefix."""
        prefix = "<resources>/user/"
        for settings in self.user_resources.values():
            if not settings.default.startswith(prefix):
                raise ValueError(
                    f"User resource pathvars must start with {prefix}. Found {settings.default}."
                )
        return self

    @model_validator(mode="after")
    def check_results(self) -> Self:
        """Ensure result pathvars follow a standard prefix."""
        prefix = "<results>/"
        for settings in self.results.values():
            if not settings.default.startswith(prefix):
                raise ValueError(
                    f"Result pathvars must start with {prefix}. Found {settings.default}."
                )
        return self


class ModuleInterface(BaseModel):
    """Schema for module INTERFACE.yaml."""

    model_config = {"extra": "forbid"}

    pathvars: Pathvars = Pathvars()
    "Snakemake pathvars, allowing module input re-wiring."
    wildcards: dict[str, str] = Field(default_factory=dict)
    "Module wildcards. If provided, these must be present in the keys of either module resources or results."
    modelblocks_convention: str = Field(pattern=SEMVER_REGEX)
    "Modelblocks convention in semantic versioning."

    @classmethod
    def from_yaml(cls, path: str | Path):
        """Initialise the schema from a YAML file."""
        with open(Path(path)) as file:
            data = yaml.safe_load(file)
        return cls(**data)

    @model_validator(mode="after")
    def check_wildcards(self) -> Self:
        """Ensure wildcards are specified in file names."""
        io_files = [i.default for i in self.pathvars.user_resources.values()]
        io_files += [i.default for i in self.pathvars.results.values()]

        filename_wildcards: set[str] = set()
        for filename in io_files:
            filename_wildcards.update(_find_between(filename, "{}"))

        diff = filename_wildcards - self.wildcards.keys()
        if diff:
            raise ValueError(
                f"Wildcards not specified in 'user_resources' or 'results' pathvars: {diff}."
            )
        diff = self.wildcards.keys() - filename_wildcards
        if diff:
            raise ValueError(f"Unused wildcards found: {diff}")
        return self

    def to_mermaid_flowchart(self, name: str) -> str:
        """Convert to a mermaid diagram."""
        mermaid_txt = dedent(f"""\
            ---
            title: {name}
            ---
            flowchart LR
            M(({name}))
            """)

        # Generate user-related part
        if self.pathvars.user_resources:
            user_txt = "\n    ".join(self.pathvars.user_resources)
            mermaid_txt += f"""C1[/"`**user**\n    {user_txt}\n    `"/] --> M\n"""

        # Generate results part
        results_txt = "\n    ".join(self.pathvars.results)
        mermaid_txt += f"""M --> O1("`**results**\n    {results_txt}\n    `")"""
        return mermaid_txt


def _modularise_snakemake_graph(
    rulegraph: nx.DiGraph, module_prefixes: list[str]
) -> nx.DiGraph:
    """Wrap module rules into a single rule with a special marker."""
    labels = nx.get_node_attributes(rulegraph, "label")
    # Ensure labels are clean strings
    labels = {key: value.replace('"', "") for key, value in labels.items()}

    modulegraph = rulegraph.copy()
    for prefix in module_prefixes:
        module_node_attrs = dict(label=prefix, color="0 0 0", style="diagonals")
        modulegraph.add_node(prefix, **module_node_attrs)

        module_nodes = set(
            key for key, value in labels.items() if value.startswith(prefix)
        )
        if not module_nodes:
            raise ValueError(f"Prefix not found: {prefix}.")
        for edge in rulegraph.edges:
            if not set(edge) - module_nodes:
                # edge is completely within the module
                modulegraph.remove_edge(*edge)
            elif edge[0] in module_nodes and edge[1] not in module_nodes:
                # edge is a module output
                modulegraph.add_edge(prefix, edge[1])
            elif edge[0] not in module_nodes and edge[1] in module_nodes:
                # edge is a module input
                modulegraph.add_edge(edge[0], prefix)

        modulegraph.remove_nodes_from(module_nodes)

    return modulegraph


def modular_rulegraph_png(
    snakemake_dotfile: Path | str, output_path: Path | str, prefixes: str | list[str]
):
    """Create a PNG file with a simplified DAG with a single rule per module.

    Args:
        snakemake_dotfile (Path | str): path to .dot file (e.g., a rulegraph).
        output_path (Path | str): location to save the resulting PNG.
        prefixes (str|list[str]): list of module prefixes to simplify.

    Raises:
        ValueError: input was not a .dot file.
    """
    if not str(snakemake_dotfile).endswith(".dot"):
        raise ValueError("Only .dot files can be processed.")
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    rulegraph = nx.DiGraph(nx.nx_pydot.read_dot(snakemake_dotfile))
    modulegraph = _modularise_snakemake_graph(rulegraph, prefixes)
    dot_graph = nx.drawing.nx_pydot.to_pydot(modulegraph)
    dot_graph.write_png(output_path)

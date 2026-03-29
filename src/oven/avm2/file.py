import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from .config import ParseMode, VerifyConfig, VerifyProfile
from .constant_pool import ConstantPool
from .methods import MethodInfo, MethodBody
from .traits import InstanceInfo, ClassInfo, ScriptInfo
from .enums import ABCFileDict, MetadataInfoDict, MetadataItemDict, MultinameKind

if TYPE_CHECKING:
    from .abc.reader import ABCReader


@dataclass
class MetadataItem:
    """Immutable metadata item."""
    key: Optional[str]
    value: str

    def to_dict(self) -> MetadataItemDict:
        return {
            "key": self.key,
            "value": self.value
        }

    def __repr__(self) -> str:
        if self.key:
            return f"MetadataItem({self.key}={self.value})"
        return f"MetadataItem({self.value})"


@dataclass
class MetadataInfo:
    """Immutable metadata block."""
    name: str
    items: List[MetadataItem]

    def to_dict(self) -> MetadataInfoDict:
        return {
            "name": self.name,
            "items": [item.to_dict() for item in self.items]
        }

    def __repr__(self) -> str:
        return f"MetadataInfo({self.name}, {len(self.items)} items)"


@dataclass
class ABCFile:
    """Immutable core ABC data model."""
    AS3_KEYWORDS = frozenset(
        [
            # Lexical keywords
            "as", "break", "case", "catch", "class", "const", "continue", "default", "delete",
            "do", "else", "extends", "false", "finally", "for", "function", "if", "implements",
            "import", "in", "instanceof", "interface", "internal", "is", "native", "new",
            "null", "package", "private", "protected", "public", "return", "super", "switch",
            "this", "throw", "to", "true", "try", "typeof", "use", "var", "void", "while", "with",
            # Syntactical keywords
            "each", "get", "set", "namespace", "include", "dynamic", "final", "override", "static",
            # Future reserved words
            "abstract", "boolean", "byte", "cast", "char", "debugger", "double", "enum", "export",
            "float", "goto", "intrinsic", "long", "prototype", "short", "synchronized", "throws",
            "transient", "type", "virtual", "volatile",
        ]
    )

    minor_version: int
    major_version: int
    constant_pool: ConstantPool
    methods: List[MethodInfo]
    metadata: List[MetadataInfo]
    instances: List[InstanceInfo]
    classes: List[ClassInfo]
    scripts: List[ScriptInfo]
    method_bodies: List[MethodBody]
    _method_body_indexes: Optional[dict[int, MethodBody]] = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def to_dict(self, resolve: bool = False) -> ABCFileDict:
        """Convert the full ABC structure into a dictionary."""
        pool = self.constant_pool if resolve else None
        return {
            "minor_version": self.minor_version,
            "major_version": self.major_version,
            "constant_pool": self.constant_pool.to_dict(pool),
            "methods": [method.to_dict(pool) for method in self.methods],
            "metadata": [meta.to_dict() for meta in self.metadata],
            "instances": [instance.to_dict() for instance in self.instances],
            "classes": [cls.to_dict() for cls in self.classes],
            "scripts": [script.to_dict() for script in self.scripts],
            "method_bodies": [body.to_dict(pool) for body in self.method_bodies]
        }

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        mode: ParseMode | str | None = None,
        verify_profile: VerifyProfile | str | None = None,
        strict_metadata_indices: bool = False,
        verify_stack: bool = False,
        verify_relaxed: bool = False,
        verify_stack_semantics: bool | None = None,
        verify_branch_targets: bool | None = None,
        strict_lookupswitch: bool | None = None,
        relax_join_depth: bool | None = None,
        relax_join_types: bool | None = None,
        prefer_precise_any_join: bool | None = None,
        precision_enhanced: bool | None = None,
        lattice_depth_policy: str | None = None,
        lattice_conflict_policy: str | None = None,
        lattice_any_policy: str | None = None,
    ) -> 'ABCFile':
        """Parse an ABC file from bytes with compatibility options."""
        resolved: VerifyConfig | None = None
        if verify_profile is not None:
            profile = (
                verify_profile
                if isinstance(verify_profile, VerifyProfile)
                else VerifyProfile(str(verify_profile))
            )
            resolved = VerifyConfig.from_verify_profile(profile)
        elif mode is not None:
            parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
            resolved = VerifyConfig.from_parse_mode(parse_mode)

        if resolved is not None:
            strict_metadata_indices = resolved.strict_metadata_indices
            verify_stack_semantics = resolved.verify_stack_semantics
            verify_branch_targets = resolved.verify_branch_targets
            verify_relaxed = resolved.verify_relaxed
            if strict_lookupswitch is None:
                strict_lookupswitch = resolved.strict_lookupswitch
            if relax_join_depth is None:
                relax_join_depth = resolved.relax_join_depth
            if relax_join_types is None:
                relax_join_types = resolved.relax_join_types
            if prefer_precise_any_join is None:
                prefer_precise_any_join = resolved.prefer_precise_any_join
            verify_stack = verify_stack or verify_stack_semantics or verify_branch_targets
        else:
            if verify_stack_semantics is None:
                verify_stack_semantics = verify_stack
            if verify_branch_targets is None:
                verify_branch_targets = verify_stack
            if strict_lookupswitch is None:
                # Keep legacy behavior in relaxed mode for malformed lookupswitch targets.
                strict_lookupswitch = not verify_relaxed
        if relax_join_depth is None:
            relax_join_depth = verify_relaxed
        if relax_join_types is None:
            relax_join_types = verify_relaxed
        if prefer_precise_any_join is None:
            prefer_precise_any_join = False
        if precision_enhanced is None:
            precision_enhanced = False

        if lattice_depth_policy is not None:
            policy = str(lattice_depth_policy).strip().lower()
            if policy == "min":
                relax_join_depth = True
            elif policy == "strict":
                relax_join_depth = False
            else:
                raise ValueError(f"Unsupported lattice_depth_policy: {lattice_depth_policy}")

        if lattice_conflict_policy is not None:
            policy = str(lattice_conflict_policy).strip().lower()
            if policy == "widen":
                relax_join_types = True
            elif policy == "strict":
                relax_join_types = False
            else:
                raise ValueError(f"Unsupported lattice_conflict_policy: {lattice_conflict_policy}")

        if lattice_any_policy is not None:
            policy = str(lattice_any_policy).strip().lower()
            if policy == "prefer_precise":
                prefer_precise_any_join = True
            elif policy == "widen":
                prefer_precise_any_join = False
            else:
                raise ValueError(f"Unsupported lattice_any_policy: {lattice_any_policy}")

        from .abc.reader import ABCReader
        reader = ABCReader(
            data,
            strict_metadata_indices=strict_metadata_indices,
            verify_stack=verify_stack,
            verify_relaxed=verify_relaxed,
            verify_stack_semantics=verify_stack_semantics,
            verify_branch_targets=verify_branch_targets,
            strict_lookupswitch=strict_lookupswitch,
            relax_join_depth=relax_join_depth,
            relax_join_types=relax_join_types,
            prefer_precise_any_join=prefer_precise_any_join,
            precision_enhanced=precision_enhanced,
        )
        return reader.read_abc_file()

    def __repr__(self) -> str:
        return (f"ABCFile(v{self.major_version}.{self.minor_version}, "
                f"methods={len(self.methods)}, classes={len(self.classes)}, "
                f"scripts={len(self.scripts)})")

    def _build_method_body_index(self) -> None:
        self._method_body_indexes = {body.method: body for body in self.method_bodies}

    def method_body_at(self, method_index: int) -> Optional[MethodBody]:
        if method_index < 0:
            raise ValueError("method_index must be >= 0")

        if self._method_body_indexes is None:
            self._build_method_body_index()

        return self._method_body_indexes.get(method_index)

    def decompile(
        self,
        method_idx: int | None = None,
        *,
        style: str = "semantic",
        layout: str = "methods",
        int_format: str = "dec",
        inline_vars: bool = False,
    ) -> str:
        """Decompile this parsed ABC in-memory."""
        from .decompiler import _decompile_abc_parsed

        return _decompile_abc_parsed(
            self,
            method_idx=method_idx,
            style=style,
            layout=layout,
            int_format=int_format,
            inline_vars=inline_vars,
        )

    def decompile_to_files(
        self,
        output_dir: str | Path,
        *,
        style: str = "semantic",
        int_format: str = "dec",
        clean_output: bool = True,
        inline_vars: bool = False,
    ) -> list[Path]:
        """Decompile this parsed ABC into `.as` files."""
        from .decompiler import _decompile_abc_parsed_to_files

        return _decompile_abc_parsed_to_files(
            self,
            output_dir,
            style=style,
            int_format=int_format,
            clean_output=clean_output,
            inline_vars=inline_vars,
        )

    def fix_names(self) -> None:
        name_set = set(self.constant_pool.strings)

        for namespace in self.constant_pool.namespaces:
            self._fix_name_index(namespace.name, name_set, is_namespace=True)

        for multiname in self.constant_pool.multinames:
            if not hasattr(multiname, "kind"):
                continue

            if multiname.kind not in (
                MultinameKind.QNAME,
                MultinameKind.QNAMEA,
                MultinameKind.MULTINAME,
                MultinameKind.MULTINAMEA,
                MultinameKind.RTQNAME,
                MultinameKind.RTQNAMEA,
            ):
                continue

            data = getattr(multiname, "data", None)
            if not isinstance(data, dict):
                continue

            name_ref = data.get("name")
            if hasattr(name_ref, "value"):
                self._fix_name_index(int(name_ref.value), name_set)
            elif isinstance(name_ref, int):
                self._fix_name_index(name_ref, name_set)

    def _fix_name_index(self, name_idx: int, name_set: set[str], is_namespace: bool = False) -> None:
        if name_idx <= 0 or name_idx > len(self.constant_pool.strings):
            return

        old_name = self.constant_pool.strings[name_idx - 1]
        if old_name in ("", "*"):
            return

        fixed_name = self._sanitize_name(old_name, is_namespace=is_namespace)
        if old_name != fixed_name or fixed_name in self.AS3_KEYWORDS:
            suffix = 0
            indexed_name = fixed_name
            while indexed_name in self.AS3_KEYWORDS or indexed_name in name_set:
                indexed_name = f"{fixed_name}_i{suffix}"
                suffix += 1

            name_set.add(indexed_name)
            self.constant_pool.strings[name_idx - 1] = indexed_name

    def _sanitize_name(self, name: str, is_namespace: bool = False) -> str:
        if is_namespace:
            if name.startswith("http://"):
                return name

            clean_parts = [self._clean_name_part(part) for part in name.split(".")]
            clean_parts = [part for part in clean_parts if part]
            return ".".join(clean_parts)

        return self._clean_name_part(name)

    @staticmethod
    def _clean_name_part(part: str) -> str:
        part = re.sub(r"^[^a-zA-Z_$]+", "", part)
        part = re.sub(r"[^a-zA-Z_$0-9:]+", "", part)
        return part

    def __str__(self) -> str:
        """Return a verbose string representation with all details."""
        lines = []
        lines.append(f"ABCFile(v{self.major_version}.{self.minor_version})")
        lines.append(f"  Methods: {len(self.methods)}")
        lines.append(f"  Classes: {len(self.classes)}")
        lines.append(f"  Scripts: {len(self.scripts)}")
        lines.append(f"  Metadata: {len(self.metadata)}")
        lines.append(f"  Instances: {len(self.instances)}")
        lines.append(f"  Method Bodies: {len(self.method_bodies)}")
        
        # Print full constant-pool details.
        lines.append("\n" + str(self.constant_pool))
        
        # Print each member block in full detail.
        if self.methods:
            lines.append("\n  Methods:")
            for i, method in enumerate(self.methods):
                lines.append(f"    [{i}] {method}")
        
        if self.classes:
            lines.append("\n  Classes:")
            for i, cls in enumerate(self.classes):
                lines.append(f"    [{i}] {cls}")
        
        if self.scripts:
            lines.append("\n  Scripts:")
            for i, script in enumerate(self.scripts):
                lines.append(f"    [{i}] {script}")
        
        if self.metadata:
            lines.append("\n  Metadata:")
            for i, meta in enumerate(self.metadata):
                lines.append(f"    [{i}] {meta}")
        
        if self.instances:
            lines.append("\n  Instances:")
            for i, instance in enumerate(self.instances):
                lines.append(f"    [{i}] {instance}")
        
        if self.method_bodies:
            lines.append("\n  Method Bodies:")
            for i, body in enumerate(self.method_bodies):
                # Reuse MethodBody.__str__ for detail output.
                body_str = str(body)
                # Indent multiline blocks for readability.
                indented_body = "\n    ".join(body_str.split("\n"))
                lines.append(f"    [{i}] {indented_body}")
        
        return "\n".join(lines)

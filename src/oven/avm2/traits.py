from dataclasses import dataclass
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from .enums import Index, TraitKind

if TYPE_CHECKING:
    from .constant_pool import ConstantPool


@dataclass
class Trait:
    """Trait data model for class/object fixed members."""
    name: str  # Resolved trait name.
    kind: TraitKind
    metadata: List[str]  # Resolved metadata names.
    is_final: bool = False
    is_override: bool = False
    data: Optional[Dict[str, Any]] = None

    def to_dict(self, pool: Optional['ConstantPool'] = None) -> Dict[str, Any]:
        """Return a serializable dictionary."""
        trait_dict = {
            "name": self.name,
            "kind": self.kind.name,
            "metadata": self.metadata,
            "is_final": self.is_final,
            "is_override": self.is_override
        }

        if self.data:
            # Keep payload values simple for downstream serialization.
            data_dict = {}
            for key, value in self.data.items():
                if isinstance(value, Index):
                    # Resolve index fields by semantic key.
                    if key == "type_name":
                        data_dict[key] = value.to_dict(pool, "multiname")
                    elif key in ("method", "class", "function"):
                        data_dict[key] = value.value
                    else:
                        data_dict[key] = value.value
                elif hasattr(value, 'to_dict'):
                    data_dict[key] = value.to_dict()
                else:
                    data_dict[key] = value
            trait_dict["data"] = data_dict

        return trait_dict

    def __repr__(self) -> str:
        base = f"Trait({self.name}: {self.kind.name}"
        if self.is_final:
            base += ", final"
        if self.is_override:
            base += ", override"
        if self.data:
            base += f", data={self.data}"
        return base + ")"


@dataclass
class InstanceInfo:
    """Immutable instance information."""
    name: str  # Resolved class name.
    super_name: str  # Resolved superclass name.
    is_sealed: bool
    is_final: bool
    is_interface: bool
    protected_namespace: Optional[str]
    interfaces: List[str]  # Resolved interface names.
    init_method: int  # Initializer method index.
    traits: List[Trait]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "super_name": self.super_name,
            "is_sealed": self.is_sealed,
            "is_final": self.is_final,
            "is_interface": self.is_interface,
            "protected_namespace": self.protected_namespace,
            "interfaces": self.interfaces,
            "init_method": self.init_method,
            "traits": [trait.to_dict() for trait in self.traits]
        }

    def __repr__(self) -> str:
        return f"InstanceInfo({self.name} extends {self.super_name}, traits={len(self.traits)})"


@dataclass
class ClassInfo:
    """Immutable class information."""
    init_method: int  # Static initializer method index.
    traits: List[Trait]  # Static members.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "init_method": self.init_method,
            "traits": [trait.to_dict() for trait in self.traits]
        }

    def __repr__(self) -> str:
        return f"ClassInfo(init={self.init_method}, static_traits={len(self.traits)})"


@dataclass
class ScriptInfo:
    """Immutable script information."""
    init_method: int  # Script initializer method index.
    traits: List[Trait]  # Script-level definitions.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "init_method": self.init_method,
            "traits": [trait.to_dict() for trait in self.traits]
        }

    def __repr__(self) -> str:
        return f"ScriptInfo(init={self.init_method}, traits={len(self.traits)})"

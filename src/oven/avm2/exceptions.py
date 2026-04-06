class AVM2Error(Exception):
    """Base exception for the AVM2 parser."""

    pass


class ABCParseError(AVM2Error):
    """ABC file parse error."""

    pass


class InvalidABCCodeError(ABCParseError):
    """Invalid ABC bytecode."""

    pass


class ConstantPoolError(ABCParseError):
    """Constant-pool parse error."""

    pass


class MethodParseError(ABCParseError):
    """Method parse error."""

    pass


class TraitParseError(ABCParseError):
    """Trait parse error."""

    pass

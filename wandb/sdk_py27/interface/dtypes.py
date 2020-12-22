import typing as t

if t.TYPE_CHECKING:
    from wandb.sdk.wandb_artifacts import Artifact as ArtifactInCreation
    from wandb.apis.public import Artifact as DownloadedArtifact


class TypeRegistry:
    """The TypeRegistry resolves python objects to Types as well as
    deserializes JSON dicts. Additional types can be registered via
    the .add call.
    """

    _types_by_name = None
    _types_by_class = None

    @staticmethod
    def types_by_name():
        if TypeRegistry._types_by_name is None:
            TypeRegistry._types_by_name = {}
        return TypeRegistry._types_by_name

    @staticmethod
    def types_by_class():
        if TypeRegistry._types_by_class is None:
            TypeRegistry._types_by_class = {}
        return TypeRegistry._types_by_class

    @staticmethod
    def add(wb_type):
        assert issubclass(wb_type, Type)
        TypeRegistry.types_by_name().update({wb_type.name: wb_type})
        TypeRegistry.types_by_class().update(
            {_type: wb_type for _type in wb_type.types}
        )

    @staticmethod
    def type_of(py_obj):
        class_handler = TypeRegistry.types_by_class().get(py_obj.__class__)
        _type = None
        if class_handler:
            _type = class_handler(py_obj)
        else:
            _type = ObjectType(py_obj)
        return _type

    @staticmethod
    def type_from_dict(
        json_dict, artifact = None
    ):
        wb_type = json_dict.get("wb_type")
        if wb_type is None:
            TypeError("json_dict must contain `wb_type` key")
        _type = TypeRegistry.types_by_name().get(wb_type)
        if _type is None:
            TypeError("missing type handler for {}".format(wb_type))
        return _type.from_json(json_dict, artifact)


class Type(object):
    """This is the most generic type which all types are subclasses.
    It provides simple serialization and deserialization as well as equality checks.
    A name class-level property must be uniquely set by subclasses.
    """

    # Subclasses must override with a unique name. This is used to identify the
    # class during serializations and deserializations
    name = ""

    # Subclasses may override with a list of `types` which this Type is capable
    # of being initialized. This is used by the Type Registry when calling `TypeRegistry.type_of`.
    # Some types will have an empty list - for example `Union`. There is no raw python type which
    # inherently maps to a Union and therefore the list should be empty.
    types = []

    # Contains the further specification of the Type
    # params: t.Dict[str, t.Any]

    def __init__(
        self,
        py_obj = None,
        params = None,
    ):
        """Initialize the type. Likely to be overridden by subtypes.

        Args:
            py_obj (any, optional): The python object to construct the type from. Defaults to None.
            params (dict, optional): [description]. The params for the type. If present, all other fields are ignored.
                This is not meant to be used be external parties, and is used by for deserialization. Defaults to None.
        """
        self.params = dict() if params is None else params

    def assign(self, py_obj = None):
        """Assign a python object to the type, returning a new type representing
        the result of the assignment.

        Must to be overridden by subclasses

        Args:
            py_obj (any, optional): Any python object which the user wishes to assign to
            this type

        Returns:
            Type: an instance of a subclass of the Type class.
        """
        raise NotImplementedError()

    def to_json(
        self, artifact = None
    ):
        """Generate a jsonable dictionary serialization the type.

        If overridden by subclass, ensure that `from_json` is equivalently overridden.

        Args:
            artifact (wandb.Artifact, optional): If the serialization is being performed
            for a particular artifact, pass that artifact. Defaults to None.

        Returns:
            dict: Representation of the type
        """
        res = {
            "wb_type": self.name,
            "params": Type._params_obj_to_json_obj(self.params, artifact),
        }
        if res["params"] is None or res["params"] == {}:
            del res["params"]

        return res

    @classmethod
    def from_json(
        cls,
        json_dict,
        artifact = None,
    ):
        """Construct a new instance of the type using a JSON dictionary equivalent to
        the kind output by `to_json`.

        If overridden by subclass, ensure that `to_json` is equivalently overridden.

        Returns:
            _Type: an instance of a subclass of the _Type class.
        """
        return cls(
            params=Type._json_obj_to_params_obj(json_dict.get("params", {}), artifact)
        )
        return cls()

    @staticmethod
    def _params_obj_to_json_obj(
        params_obj, artifact = None,
    ):
        """Helper method"""
        if params_obj.__class__ == dict:
            return {
                key: Type._params_obj_to_json_obj(params_obj[key], artifact)
                for key in params_obj
            }
        elif params_obj.__class__ == list:
            return [Type._params_obj_to_json_obj(item, artifact) for item in params_obj]
        elif isinstance(params_obj, Type):
            return params_obj.to_json(artifact)
        else:
            return params_obj

    @staticmethod
    def _json_obj_to_params_obj(
        json_obj, artifact = None
    ):
        """Helper method"""
        if json_obj.__class__ == dict:
            if "wb_type" in json_obj:
                return TypeRegistry.type_from_dict(json_obj, artifact)
            else:
                return {
                    key: Type._json_obj_to_params_obj(json_obj[key], artifact)
                    for key in json_obj
                }
        elif json_obj.__class__ == list:
            return [Type._json_obj_to_params_obj(item, artifact) for item in json_obj]
        else:
            return json_obj

    def __repr__(self):
        return "<WBType:{} | {}>".format(self.name, self.params)

    def __eq__(self, other):
        return self is other or (
            isinstance(self, Type)
            and isinstance(other, Type)
            and self.to_json() == other.to_json()
        )


class _NeverType(Type):
    """all assignments to a NeverType result in a Never Type.
    NeverType is basically the invalid case
    """

    name = "never"
    types = []

    def assign(self, py_obj = None):
        return self


# Singleton helper
NeverType = _NeverType()


class _AnyType(Type):
    """all assignments to an AnyType result in the
    AnyType except None which will be NeverType
    """

    name = "any"
    types = []

    def assign(
        self, py_obj = None
    ):
        return self if py_obj is not None else NeverType


class _UnknownType(Type):
    """all assignments to an UnknownType result in the type of the assigned object
    except none which will result in a NeverType
    """

    name = "unknown"
    types = []

    def assign(self, py_obj = None):
        return NeverType if py_obj is None else TypeRegistry.type_of(py_obj)


class _NoneType(Type):
    name = "none"
    types = [None.__class__]

    def assign(
        self, py_obj = None
    ):
        return self if py_obj is None else NeverType


class _TextType(Type):
    name = "text"
    types = [str]

    def assign(
        self, py_obj = None
    ):
        return self if py_obj.__class__ == str else NeverType


class _NumberType(Type):
    name = "number"
    types = [int, float]

    def assign(
        self, py_obj = None
    ):
        return self if py_obj.__class__ in [int, float] else NeverType


class _BooleanType(Type):
    name = "boolean"
    types = [bool]

    def assign(
        self, py_obj = None
    ):
        return self if py_obj.__class__ == bool else NeverType


# Singleton Helpers
AnyType = _AnyType()
UnknownType = _UnknownType()
NoneType = _NoneType()
TextType = _TextType()
NumberType = _NumberType()
BooleanType = _BooleanType()


class UnionType(Type):
    """Represents an "or" of types
    """

    name = "union"
    types = []

    def __init__(
        self,
        py_obj = None,
        params = None,
    ):
        if py_obj is None and params is None:
            raise TypeError("Both py_obj and params cannot be none")
        assert py_obj is None or (
            py_obj.__class__ == list
            and all([isinstance(item, Type) for item in py_obj])
        )
        assert params is None or (
            params.__class__ == dict
            and all(
                [isinstance(item, Type) for item in params.get("allowed_types", [])]
            )
        )

        if params is None:
            params = {"allowed_types": py_obj}

        params["allowed_types"] = UnionType._flatten_types(params["allowed_types"])
        params["allowed_types"].sort(key=str)

        super(UnionType, self).__init__(py_obj, params)

    def assign(self, py_obj = None):
        resolved_types = []
        valid = False
        unknown_count = 0

        for allowed_type in self.params.get("allowed_types", []):
            if valid:
                resolved_types.append(allowed_type)
            else:
                if isinstance(allowed_type, _UnknownType):
                    unknown_count += 1
                else:
                    assigned_type = allowed_type.assign(py_obj)
                    if assigned_type == NeverType:
                        resolved_types.append(allowed_type)
                    else:
                        resolved_types.append(assigned_type)
                        valid = True

        if not valid:
            if unknown_count == 0:
                return NeverType
            else:
                new_type = UnknownType.assign(py_obj)
                if new_type == NeverType:
                    return NeverType
                else:
                    resolved_types.append(new_type)
                    unknown_count -= 1

        for _ in range(unknown_count):
            resolved_types.append(UnknownType)

        resolved_types = UnionType._flatten_types(resolved_types)
        resolved_types.sort(key=str)
        return self.__class__(resolved_types)

    @staticmethod
    def _flatten_types(allowed_types):
        final_types = []
        for allowed_type in allowed_types:
            if isinstance(allowed_type, UnionType):
                internal_types = UnionType._flatten_types(
                    allowed_type.params["allowed_types"]
                )
                for internal_type in internal_types:
                    final_types.append(internal_type)
            else:
                final_types.append(allowed_type)
        return final_types


def OptionalType(wb_type):  # noqa: N802
    """Function that mimics the Type class API for constructing an "Optional Type"
    which is just a Union[wb_type, NoneType]

    Args:
        wb_type (Type): type to be optional

    Returns:
        Type: Optional version of the type.
    """
    return UnionType([wb_type, NoneType])


class ObjectType(Type):
    """Serves as a backup type by keeping track of the python object name"""

    name = "object"
    types = []

    def __init__(
        self,
        py_obj = None,
        params = None,
    ):
        if py_obj is None and params is None:
            raise TypeError("Both py_obj and params cannot be none")
        assert params is None or (
            params.__class__ == dict and len(params.get("class_name", "")) > 0
        )

        if params is None:
            params = {"class_name": py_obj.__class__.__name__}

        super(ObjectType, self).__init__(py_obj, params)

    def assign(self, py_obj = None):
        if py_obj.__class__.__name__ == self.params["class_name"]:
            return self
        else:
            return NeverType


class ListType(Type):
    """Represents a list of homogenous types
    """

    name = "list"
    types = [list, tuple, set, frozenset]

    def __init__(
        self,
        py_obj = None,
        dtype = None,
        params = None,
    ):
        """Initialize the ListType.

        Args:
            py_obj (any, optional): The python object to construct the type from. Defaults to None.
            dtype (Type, optional); The dtype of the list. Overrides py_obj
            params (dict, optional): [description]. The params for the type. If present, all other fields are ignored.
                This is not meant to be used be external parties, and is used by for deserialization. Defaults to None.
        """
        assert py_obj is None or py_obj.__class__ in [list, tuple, set, frozenset]

        assert params is None or (
            params.__class__ == dict and isinstance(params.get("element_type"), Type)
        )

        assert dtype is None or isinstance(dtype, Type)

        if params is None:
            if dtype is not None:
                params = {"element_type": dtype}
            elif py_obj is None:
                params = {"element_type": UnknownType}
            elif (  # yes, this is a bit verbose, but the mypy typechecker likes it this way
                isinstance(py_obj, list)
                or isinstance(py_obj, tuple)
                or isinstance(py_obj, set)
                or isinstance(py_obj, frozenset)
            ):
                py_list = list(py_obj)
                elm_type = (
                    UnknownType if None not in py_list else OptionalType(UnknownType)
                )
                for item in py_list:
                    _elm_type = elm_type.assign(item)
                    if _elm_type is NeverType:
                        raise TypeError(
                            "List contained incompatible types. Expected type {} found item {}".format(
                                elm_type, item
                            )
                        )

                    elm_type = _elm_type

                params = {"element_type": elm_type}

        super(ListType, self).__init__(py_obj, params)

    def assign(self, py_obj = None):
        if py_obj is None or py_obj.__class__ not in self.types:
            return NeverType

        new_element_type = self.params["element_type"]
        for obj in py_obj:
            new_element_type = new_element_type.assign(obj)
            if new_element_type == NeverType:
                return NeverType
        return ListType(dtype=new_element_type)


class KeyPolicy:
    EXACT = "E"  # require exact key match
    SUBSET = "S"  # all known keys are optional and unknown keys are disallowed
    UNRESTRICTED = "U"  # all known keys are optional and unknown keys are Unknown


# KeyPolicyType = t.Literal[KeyPolicy.EXACT, KeyPolicy.SUBSET, KeyPolicy.UNRESTRICTED]


class DictType(Type):
    """Represents a dictionary object where each key can have a type
    """

    name = "dictionary"
    types = [dict]

    def __init__(
        self,
        py_obj = None,
        key_policy = KeyPolicy.EXACT,
        dtype = None,
        params = None,
    ):
        """Initialize the DictType.

        Args:
            py_obj (any, optional): The python object to construct the type from. Defaults to None.
            key_policy (str): Key policy from KeyPolicy
                ```
                    EXACT = "E"  # require exact key match
                    SUBSET = "S"  # all known keys are optional and unknown keys are disallowed
                    UNRESTRICTED = "U"  # all known keys are optional and unknown keys are Unknown
                ```
            dtype (dict, optional): A dict-like object with values for each key as either a dictionary, Type, or list. Will override py_obj.
            params (dict, optional): The params for the type. If present, all other fields are ignored.
                This is not meant to be used be external parties, and is used by for deserialization. Defaults to None.
        """
        # TODO Parameter validation
        if params is None:
            if dtype is not None:
                new_type_map = {}
                for key in dtype:
                    # Allows for nested dict notation
                    if dtype[key].__class__ == dict:
                        new_type_map[key] = DictType(
                            dtype=dtype[key], key_policy=key_policy
                        )
                    # allows for nested list notation
                    elif dtype[key].__class__ == list:
                        ptr = dtype[key]
                        depth = 0
                        while ptr.__class__ == list and len(ptr) > 0:
                            if len(ptr) > 1:
                                raise TypeError(
                                    "Lists in DictType's dtype must be of length 0 or 1"
                                )
                            else:
                                depth += 1
                                ptr = ptr[0]

                        if ptr.__class__ == list:
                            inner_type = ListType()
                        elif ptr.__class__ == dict:
                            inner_type = DictType(dtype=ptr, key_policy=key_policy)
                        elif isinstance(ptr, Type):
                            inner_type = ptr
                        else:
                            raise TypeError(
                                "DictType dtype values must subclass Type (or be a dict or list). Found {} of class {}".format(
                                    dtype[key], dtype[key].__class__
                                )
                            )
                        for _ in range(depth):
                            inner_type = ListType(dtype=inner_type)
                        new_type_map[key] = inner_type
                    elif isinstance(dtype[key], Type):
                        new_type_map[key] = dtype[key]
                    else:
                        raise TypeError(
                            "DictType dtype values must subclass Type (or be a dict or list). Found {} of class {}".format(
                                dtype[key], dtype[key].__class__
                            )
                        )
                params = {"type_map": new_type_map, "policy": key_policy}
            elif py_obj is not None:
                params = {
                    "type_map": {
                        key: TypeRegistry.type_of(py_obj[key]) for key in py_obj
                    },
                    "policy": key_policy,
                }
            else:
                params = {"type_map": {}, "policy": key_policy}

        super(DictType, self).__init__(py_obj, params)

    def assign(self, py_obj = None):
        if py_obj is None or py_obj.__class__ not in self.types:
            return NeverType

        new_type_map = {}
        type_map = self.params.get("type_map", {})
        policy = self.params.get("policy", KeyPolicy.EXACT)

        for key in type_map:
            if key in py_obj:
                new_type = type_map[key].assign(py_obj[key])
                if new_type == NeverType:
                    return NeverType
                else:
                    new_type_map[key] = new_type
            else:
                # Treat a missing key as if it is a None value.
                new_type = type_map[key].assign(None)
                if new_type == NeverType:
                    if policy in [KeyPolicy.EXACT]:
                        return NeverType
                    elif policy in [KeyPolicy.SUBSET, KeyPolicy.UNRESTRICTED]:
                        new_type_map[key] = type_map[key]
                else:
                    new_type_map[key] = new_type

        for key in py_obj:
            if key not in new_type_map:
                if policy in [KeyPolicy.EXACT, KeyPolicy.SUBSET]:
                    return NeverType
                elif policy in [KeyPolicy.UNRESTRICTED]:
                    if py_obj[key].__class__ == dict:
                        new_type_map[key] = DictType(py_obj[key], policy)
                    else:
                        new_type_map[key] = TypeRegistry.type_of(py_obj[key])

        return DictType(dtype=new_type_map, key_policy=policy)


class ConstType(Type):
    """Represents a constant value (currently only primitives supported)
    """

    name = "const"
    types = []
    _const_supported_types = [str, int, float, bool, set]

    def __init__(
        self,
        py_obj = None,
        params = None,
    ):
        if py_obj is None and params is None:
            raise TypeError("Both py_obj and params cannot be none")
        assert py_obj.__class__ in self._const_supported_types
        assert params is None or (params.__class__ == dict and params.get("val"))

        if params is None:
            params = {"val": py_obj}
            if isinstance(py_obj, set):
                params["is_set"] = True
        else:
            if params.get("is_set", False):
                params["val"] = set(params["val"])

        super(ConstType, self).__init__(py_obj, params)

    def assign(self, py_obj = None):
        valid = self.params.get("val") == py_obj
        return self if valid else NeverType


# Special Types
TypeRegistry.add(_NeverType)
TypeRegistry.add(_AnyType)
TypeRegistry.add(_UnknownType)

# Types with default type mappings
TypeRegistry.add(_NoneType)
TypeRegistry.add(_TextType)
TypeRegistry.add(_NumberType)
TypeRegistry.add(_BooleanType)
TypeRegistry.add(ListType)
TypeRegistry.add(DictType)

# Types without default type mappings
TypeRegistry.add(UnionType)
TypeRegistry.add(ObjectType)
TypeRegistry.add(ConstType)

__all__ = [
    "TypeRegistry",
    "NeverType",
    "UnknownType",
    "AnyType",
    "NoneType",
    "TextType",
    "NumberType",
    "BooleanType",
    "ListType",
    "DictType",
    "KeyPolicy",
    "UnionType",
    "ObjectType",
    "ConstType",
    "OptionalType",
    "Type",
]

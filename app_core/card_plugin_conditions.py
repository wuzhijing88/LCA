"""脚本卡片输入的静态校验与资源装卸状态。"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal

from app_core.card_plugins import BUNDLE_PARAMETER, CardPluginError, input_parameter_key, validate_value


@dataclass(frozen=True)
class ParameterState:
    visible: bool
    enabled: bool
    required: bool

    @property
    def active(self):
        return self.visible and self.enabled


@dataclass
class ParameterResolution:
    values: dict
    definitions: dict
    states: dict
    pending: set
    errors: dict


def resolve_parameters(definitions, values):
    if set(values) != set(definitions):
        raise CardPluginError("插件输入缺失或包含未声明的参数")
    states = {name: ParameterState(True, True, definition["required"]) for name, definition in definitions.items()}
    return ParameterResolution(copy.deepcopy(values), copy.deepcopy(definitions), states, set(), {})


def parameter_states(definitions, values):
    return resolve_parameters(definitions, values).states


def validate_effective_value(value, definition, label):
    result = validate_value(value, definition, label)
    if definition["type"] == "float" and "decimals" in definition:
        places = max(0, -Decimal(str(result)).normalize().as_tuple().exponent)
        if places > definition["decimals"]:
            raise CardPluginError(f"{label}不能超过 {definition['decimals']} 位小数")
    return result


def validate_inputs(definitions, values, *, allow_unresolved=False, require_complete=True):
    from task_workflow.expr import contains_interpolation

    resolution = resolve_parameters(definitions, values)
    for name, definition in definitions.items():
        value = resolution.values[name]
        if allow_unresolved and isinstance(value, str) and contains_interpolation(value):
            continue
        resolution.values[name] = validate_effective_value(
            value, {**definition, "required": definition["required"] if require_complete else False}, f"参数 {name}",
        )
    return resolution.values, resolution.states


def prepare_parameter_storage(definitions, parameters):
    return parameter_states(definitions, values_from_parameters(definitions, parameters))


def values_from_parameters(definitions, parameters):
    expected = {BUNDLE_PARAMETER, *(input_parameter_key(name) for name in definitions)}
    if not isinstance(parameters, dict) or set(parameters) != expected:
        raise CardPluginError("插件输入缺失或包含未声明的参数")
    return {name: parameters[input_parameter_key(name)] for name in definitions}


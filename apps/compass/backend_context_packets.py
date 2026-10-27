"""Lossless, budget-bounded transport planning. No inference or publication.

This internal format is not enabled in the production executor. A future
executor must finish every packet, check all citations and conflicts globally,
and pass its own real-model quality gate before publishing any result.
"""
from copy import deepcopy
import hashlib
import json

from . import backend_model as model

VERSION = 'context-packets-v1'
PREFIX = ('Transport: units.text_index resolves texts; occurrences contain unit_id, original_position, metadata_index. '
          'Unit IDs are unchanged. This packet is part of one full history, not a complete '
          'patient. Do not infer absence from packet boundaries. Return only local evidence.\n')
MAX_PACKETS = 64


class PacketError(ValueError):
    def __init__(self, code, unit_index=None):
        self.code, self.unit_index = code, unit_index
        super().__init__(code)  # No clinical text or provider data in errors.


def digest(value):
    try:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, UnicodeError):
        raise PacketError('invalid_payload') from None


def _validate(payload):
    if (type(payload) is not dict or type(payload.get('task')) is not str
            or payload.get('columns') != ['unit_id', 'text', 'categories', 'code', 'metadata_index']
            or type(payload.get('units')) is not list or type(payload.get('metadata')) is not list
            or type(payload.get('metadata_columns')) is not list
            or set(payload) & {'texts', 'transport', 'occurrence_columns'}):
        raise PacketError('unsupported_payload')
    digest(payload)
    ids = set()
    for i, row in enumerate(payload['units']):
        if (type(row) is not list or len(row) != 5 or type(row[0]) is not str
                or not row[0] or row[0] in ids or type(row[1]) is not str
                or type(row[4]) is not int or not 0 <= row[4] < len(payload['metadata'])):
            raise PacketError('invalid_unit', i)
        ids.add(row[0])
    if any(type(row) is not list or len(row) != len(payload['metadata_columns']) for row in payload['metadata']):
        raise PacketError('invalid_metadata')


def _groups(payload):
    groups, indexes = [], {}
    for position, row in enumerate(payload['units']):
        key = digest(row[1:4])
        if key not in indexes:
            indexes[key] = len(groups)
            groups.append([deepcopy(row[1:4]), []])
        groups[indexes[key]][1].append([row[0], position, row[4]])
    return groups


def _packet(payload, groups, source, start, stop, index, count):
    texts, text_index, metadata, metadata_index, original_indexes, units = [], {}, [], {}, [], []
    for fields, occurrences in groups[start:stop]:
        if fields[0] not in text_index:
            text_index[fields[0]] = len(texts)
            texts.append(fields[0])
        packed = []
        for uid, position, meta in occurrences:
            if meta not in metadata_index:
                metadata_index[meta] = len(metadata)
                metadata.append(deepcopy(payload['metadata'][meta]))
                original_indexes.append(meta)
            packed.append([uid, position, metadata_index[meta]])
        units.append([text_index[fields[0]], *deepcopy(fields[1:]), packed])
    value = deepcopy({k: v for k, v in payload.items() if k not in ('units', 'metadata')})
    value.update(task=PREFIX + payload['task'], columns=['text_index', 'categories', 'code', 'occurrences'],
        occurrence_columns=['unit_id', 'original_position', 'metadata_index'], texts=texts, units=units, metadata=metadata,
        transport={'version': VERSION, 'source_sha256': source, 'packet_index': index,
                   'packet_count': count, 'group_start': start, 'group_stop': stop,
                   'total_groups': len(groups), 'total_units': len(payload['units']), 'metadata_indexes': original_indexes})
    return value


def prepare(payload, schema, config, *, max_packets=MAX_PACKETS, split_occurrences=False, request_transform=None):
    """Pack exact field groups with every original occurrence; fail rather than cut text or history.

    Both byte and conservative per-call cost limits use the existing adapter's
    exact preflight. Worst-case packet numbering is included while sizing.
    Total reservation is reported separately and never increases account caps.
    """
    _validate(payload)
    if type(max_packets) is not int or not 1 <= max_packets <= MAX_PACKETS:
        raise PacketError('invalid_packet_limit')
    source = digest(payload)
    render = request_transform or (lambda value: value)
    groups = _groups(payload)
    if split_occurrences:
        # A repeated field may have hundreds of independently dated occurrences.
        # Splitting their index list keeps every entire source unit and its text.
        expanded = []
        for fields, occurrences in groups:
            current = []
            for occurrence in occurrences:
                candidate = _packet(payload, [[fields, current + [occurrence]]], source, 0, 1, max_packets, max_packets)
                candidate['transport']['total_groups'] = len(payload['units'])
                try:
                    model.preflight(render(candidate), schema, config)
                except model.ModelError as exc:
                    if exc.code not in ('context_limit', 'call_cost_limit'):
                        raise
                    if not current:
                        raise PacketError('unit_exceeds_limit', occurrence[1]) from None
                    expanded.append([deepcopy(fields), current])
                    current = [occurrence]
                    single = _packet(payload, [[fields, current]], source, 0, 1, max_packets, max_packets)
                    single['transport']['total_groups'] = len(payload['units'])
                    try:
                        model.preflight(render(single), schema, config)
                    except model.ModelError:
                        raise PacketError('unit_exceeds_limit', occurrence[1]) from None
                else:
                    current.append(occurrence)
            if current:
                expanded.append([deepcopy(fields), current])
        groups = expanded
    def fits(start, stop):
        packet = _packet(payload, groups, source, start, stop, max_packets, max_packets)
        try:
            model.preflight(render(packet), schema, config)
            return True
        except model.ModelError as exc:
            if exc.code not in ('context_limit', 'call_cost_limit'):
                raise
            return False
    if not fits(0, 0):
        raise PacketError('base_exceeds_limit')
    ranges, start, stop = [], 0, 0
    total = len(groups)
    while stop < total:
        if fits(start, stop + 1):
            stop += 1
            continue
        if stop == start:
            raise PacketError('unit_exceeds_limit', groups[start][1][0][1])
        ranges.append((start, stop))
        if len(ranges) >= max_packets:
            raise PacketError('packet_count_exceeded')
        start = stop
    ranges.append((start, stop))
    packets = [_packet(payload, groups, source, a, b, i + 1, len(ranges)) for i, (a, b) in enumerate(ranges)]
    measured = [model.preflight(render(p), schema, config) for p in packets]
    plan = {'version': VERSION, 'source_sha256': source, 'total_units': len(payload['units']), 'total_groups': total,
            'base': deepcopy({k: v for k, v in payload.items() if k not in ('units', 'metadata')}),
            # Server-side manifest only. Never send this full table a second time.
            'original_metadata': deepcopy(payload['metadata']), 'packets': packets,
            'packet_sha256': [digest(p) for p in packets],
            'measurements': [{k: m[k] for k in ('input_bytes', 'reservation_micro_usd', 'schema_sha256')} for m in measured],
            'total_reservation_micro_usd': sum(m['reservation_micro_usd'] for m in measured),
            'limits': {'max_input_bytes': config.max_input_bytes, 'per_call_micro_usd': config.per_call_micro_usd,
                       'max_output_tokens': config.max_output_tokens, 'max_packets': max_packets}}
    if restore(plan, expected_sha256=source) != payload:
        raise PacketError('roundtrip_mismatch')
    return plan


def restore(plan, *, expected_sha256):
    """Reconstruct and verify against an independently pinned original digest.

    Hashes detect accidental corruption; they are not a signature. The caller
    must obtain expected_sha256 from its trusted frozen source, not this plan.
    """
    try:
        if (plan['version'] != VERSION or plan['source_sha256'] != expected_sha256
                or type(plan['packets']) is not list or not 1 <= len(plan['packets']) <= MAX_PACKETS
                or len(plan['packet_sha256']) != len(plan['packets'])):
            raise PacketError('invalid_manifest')
        base = deepcopy(plan['base'])
        metadata, units, positions = deepcopy(plan['original_metadata']), [], set()
        next_group = 0
        count = len(plan['packets'])
        for index, packet in enumerate(plan['packets'], 1):
            t = packet['transport']
            if (digest(packet) != plan['packet_sha256'][index - 1] or t['version'] != VERSION
                    or t['source_sha256'] != expected_sha256 or t['packet_index'] != index
                    or t['packet_count'] != count or t['group_start'] != next_group
                    or t['total_groups'] != plan['total_groups']
                    or t['total_units'] != plan['total_units']
                    or t['group_stop'] - t['group_start'] != len(packet['units'])
                    or len(t['metadata_indexes']) != len(packet['metadata'])):
                raise PacketError('packet_integrity')
            packet_base = {k: deepcopy(v) for k, v in packet.items() if k not in ('units', 'metadata', 'texts', 'transport', 'occurrence_columns')}
            if not packet_base['task'].startswith(PREFIX):
                raise PacketError('packet_base_mismatch')
            packet_base['task'] = packet_base['task'].removeprefix(PREFIX)
            packet_base['columns'] = ['unit_id', 'text', 'categories', 'code', 'metadata_index']
            if packet_base != base:
                raise PacketError('packet_base_mismatch')
            for local, original in enumerate(t['metadata_indexes']):
                if type(original) is not int or not 0 <= original < len(metadata) or packet['metadata'][local] != metadata[original]:
                    raise PacketError('metadata_integrity')
            if packet['columns'] != ['text_index', 'categories', 'code', 'occurrences'] or packet['occurrence_columns'] != ['unit_id', 'original_position', 'metadata_index']:
                raise PacketError('unit_integrity')
            for row in packet['units']:
                if (type(row) is not list or len(row) != 4 or type(row[0]) is not int
                        or not 0 <= row[0] < len(packet['texts']) or type(row[3]) is not list or not row[3]):
                    raise PacketError('unit_integrity')
                for occurrence in row[3]:
                    uid, position, meta = occurrence
                    if (type(position) is not int or position in positions or not 0 <= position < plan['total_units']
                            or type(meta) is not int or not 0 <= meta < len(t['metadata_indexes'])):
                        raise PacketError('unit_integrity')
                    positions.add(position)
                    units.append((position, [uid, packet['texts'][row[0]], *deepcopy(row[1:3]), t['metadata_indexes'][meta]]))
            next_group = t['group_stop']
        if next_group != plan['total_groups']:
            raise PacketError('source_integrity')
        units = [row for _, row in sorted(units)]
        value = {**base, 'units': units, 'metadata': metadata}
        _validate(value)
        if len(units) != plan['total_units'] or digest(value) != expected_sha256:
            raise PacketError('source_integrity')
        return value
    except PacketError:
        raise
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise PacketError('invalid_manifest') from None

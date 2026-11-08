"""Bounded native PowerPoint admission/extraction; no renderer or linked fetches.

The maintained reader is used only after a complete independent package walk.
The parent only handles the bounded worker protocol and the public mirror.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import struct
import zipfile
import zlib
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .errors import ConversionOperationalError
from .slide_mirror import PPTX_MEDIA_TYPE, SLIDE_FORMAT, assemble_slides, split_slides

MAX_INPUT = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_XML = 16 * 1024 * 1024
MAX_PART_XML = 8 * 1024 * 1024
MAX_OUTPUT = 16 * 1024 * 1024
MAX_ASSET = 64 * 1024 * 1024
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006"
A = _DRAWING + "/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_SHAPE_TAGS = frozenset(
    f"{{{P}}}{kind}" for kind in ("sp", "grpSp", "pic", "graphicFrame", "cxnSp")
)
_SHAPE_METADATA = frozenset(f"{{{P}}}{kind}" for kind in ("nvGrpSpPr", "grpSpPr", "extLst"))
_OOXML_MEDIA = "application/vnd.openxmlformats-officedocument.presentationml"
_MS_MEDIA = "application/vnd.ms-powerpoint"
_MAIN_TYPES = {
    PPTX_MEDIA_TYPE + ".main+xml": PPTX_MEDIA_TYPE,
    **{
        f"{_OOXML_MEDIA}.{kind}.main+xml": f"{_OOXML_MEDIA}.{kind}"
        for kind in ("slideshow", "template")
    },
    **{
        f"{_MS_MEDIA}.{kind}.macroEnabled.main+xml": f"{_MS_MEDIA}.{kind}.macroEnabled.12"
        for kind in ("presentation", "slideshow", "template")
    },
}


class PresentationError(ConversionOperationalError):
    """A malformed presentation; diagnostics deliberately omit source XML/URLs."""

    default_code = "malformed-package"

    def __init__(self, message: str, *, code: str | None = None):
        self.code = code or self.default_code
        super().__init__(message)


class PresentationLimitError(PresentationError):
    """A resource boundary refused the entire job, without partial-success output."""

    default_code = "resource-limit"


class PresentationUnavailable(PresentationError):
    """The required receiving-host containment or reader capability is unavailable."""

    default_code = "capability-unavailable"


class UnsupportedPresentation(PresentationError):
    """A proven package family lies outside the initial native profile."""

    def __init__(self, media_type: str, reason: str):
        self.media_type, self.reason = media_type, reason
        super().__init__(reason)


def presentation_family(media_type: str) -> bool:
    return (
        media_type.startswith("application/vnd.openxmlformats-officedocument.presentationml.")
        or media_type.startswith("application/vnd.ms-powerpoint.")
        or media_type == "application/vnd.ms-powerpoint"
    )


def _safe_name(name: str) -> bool:
    decoded = unquote(name)
    return bool(
        name
        and "\x00" not in name
        and "\\" not in decoded
        and not decoded.startswith("/")
        and not any(x in {"", ".", ".."} for x in decoded.split("/"))
        and posixpath.normpath(name) == name
        and ":" not in decoded
    )


def _target(owner: str, target: str) -> str:
    uri = urlsplit(target)
    if uri.scheme or uri.netloc or uri.query or uri.fragment or "\\" in unquote(target):
        raise PresentationError("presentation internal relationship is not a package part")
    name = posixpath.normpath(
        target.lstrip("/")
        if target.startswith("/")
        else posixpath.join(posixpath.dirname(owner), target)
    )
    if not _safe_name(name):
        raise PresentationError("presentation relationship escapes the package")
    return name


def _owner(name: str) -> str:
    if name == "_rels/.rels":
        return ""
    parent, filename = posixpath.split(name)
    if posixpath.basename(parent) != "_rels" or not filename.endswith(".rels"):
        raise PresentationError("malformed presentation relationship part")
    return posixpath.join(posixpath.dirname(parent), filename[:-5])


def _admit(blob: bytes) -> dict:
    from lxml import etree

    if blob.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise UnsupportedPresentation("application/x-ole-storage", "compound-binary-office-package")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            infos = archive.infolist()
            if len(infos) > 4096:
                raise PresentationLimitError("presentation archive member limit exceeded")
            parts, total, names = {}, 0, set()
            for info in infos:
                name = info.filename.rstrip("/") if info.is_dir() else info.filename
                if name.casefold() in names:
                    raise PresentationError(
                        "duplicate presentation member", code="duplicate-member"
                    )
                if not _safe_name(info.orig_filename.rstrip("/")) or not _safe_name(name):
                    raise PresentationError("unsafe presentation member", code="unsafe-member")
                names.add(name.casefold())
                if info.flag_bits & 1:
                    raise UnsupportedPresentation("application/zip", "encrypted-office-package")
                if info.is_dir():
                    continue
                if info.file_size > MAX_ASSET or total + info.file_size > MAX_EXPANDED:
                    raise PresentationLimitError(
                        "presentation expansion limit exceeded", code="expanded-byte-limit"
                    )
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise UnsupportedPresentation("application/zip", "unsupported-zip-compression")
                if info.header_offset < 0:
                    raise PresentationError("invalid presentation member offset")
                local = struct.unpack_from("<4s5H3I2H", blob, info.header_offset)
                if local[0] != b"PK\x03\x04" or local[3] != info.compress_type:
                    raise PresentationError("inconsistent presentation member header")
                if local[2] & 1:
                    raise UnsupportedPresentation("application/zip", "encrypted-office-package")
                start = info.header_offset + 30 + local[9] + local[10]
                end = start + info.compress_size
                if not 0 <= start <= end <= len(blob):
                    raise PresentationError("invalid presentation compressed member span")
                # Keep the public reader's local-name and overlap checks, but
                # never consume its metadata-limited ZipExtFile output: that
                # reader can truncate expansion to a forged file_size.
                with archive.open(info):
                    pass
                ceiling = min(MAX_ASSET, MAX_EXPANDED - total)
                if info.compress_type == zipfile.ZIP_STORED:
                    if end - start > ceiling:
                        raise PresentationLimitError(
                            "presentation actual expansion limit exceeded",
                            code="expanded-byte-limit",
                        )
                    data = blob[start:end]
                else:
                    decoder, expanded = zlib.decompressobj(-15), bytearray()
                    cursor = start
                    while cursor < end:
                        chunk = blob[cursor : min(cursor + 65536, end)]
                        cursor += len(chunk)
                        while chunk:
                            value = decoder.decompress(chunk, ceiling - len(expanded) + 1)
                            expanded.extend(value)
                            if len(expanded) > ceiling:
                                raise PresentationLimitError(
                                    "presentation actual expansion limit exceeded",
                                    code="expanded-byte-limit",
                                )
                            tail = decoder.unconsumed_tail
                            if decoder.eof:
                                if decoder.unused_data or tail or cursor != end:
                                    raise PresentationError(
                                        "presentation member has trailing compressed data"
                                    )
                                break
                            if tail == chunk and not value:
                                raise PresentationError(
                                    "presentation decompressor made no progress"
                                )
                            chunk = tail
                    if not decoder.eof:
                        raise PresentationError("presentation compressed member is truncated")
                    data = bytes(expanded)
                if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
                    raise PresentationError(
                        "presentation member size or checksum is inconsistent",
                        code="member-integrity",
                    )
                total += len(data)
                if len(data) > MAX_ASSET or total > MAX_EXPANDED:
                    raise PresentationLimitError("presentation actual expansion limit exceeded")
                parts[name] = data
    except NotImplementedError as exc:
        raise UnsupportedPresentation("application/zip", "unsupported-zip-feature") from exc
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, zlib.error, struct.error) as exc:
        raise PresentationError("malformed presentation ZIP container") from exc

    trees, xml_bytes, elements, shapes = {}, 0, 0, 0

    def parse(name: str):
        nonlocal xml_bytes, elements, shapes
        if name in trees:
            return trees[name]
        data = parts.get(name)
        if data is None:
            raise PresentationError("presentation required part is absent")
        xml_bytes += len(data)
        if len(data) > MAX_PART_XML or xml_bytes > MAX_XML:
            raise PresentationLimitError(
                "presentation XML byte limit exceeded", code="xml-byte-limit"
            )
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )
        try:
            root = etree.fromstring(data, parser)
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise PresentationError("malformed or excessive presentation XML") from exc
        if root.getroottree().docinfo.doctype:
            raise PresentationError(
                "presentation DTD/entity declarations are refused", code="xml-doctype"
            )
        stack = [(root, 1)]
        while stack:
            node, depth = stack.pop()
            elements += 1
            if node.tag in _SHAPE_TAGS or node.tag == f"{{{P}}}contentPart":
                shapes += 1
                if shapes > 20000:
                    raise PresentationLimitError("presentation total shape limit exceeded")
            if depth > 128 or elements > 200000:
                raise PresentationLimitError("presentation XML structure limit exceeded")
            stack.extend((child, depth + 1) for child in node)
        trees[name] = root
        return root

    types = parse("[Content_Types].xml")
    if types.tag != f"{{{CT}}}Types":
        raise PresentationError("invalid presentation content-type namespace")
    defaults, overrides = {}, {}
    part_names = {name.casefold(): name for name in parts}
    for element in types:
        kind = element.tag
        if kind == f"{{{CT}}}Default":
            key, content = element.get("Extension", "").casefold(), element.get("ContentType")
            if not key or not content or key in defaults:
                raise PresentationError("ambiguous presentation default content type")
            defaults[key] = content
        elif kind == f"{{{CT}}}Override":
            part, content = element.get("PartName", ""), element.get("ContentType")
            if not part.startswith("/") or not _safe_name(part[1:]) or not content:
                raise PresentationError("invalid presentation content-type override")
            key = part[1:].casefold()
            if key in overrides or key not in part_names:
                raise PresentationError("duplicate or unresolved presentation content type")
            overrides[key] = content
        else:
            raise PresentationError("unknown presentation content-type declaration")
    content_types = {}
    for name in parts:
        if name == "[Content_Types].xml":
            continue
        content = overrides.get(name.casefold()) or defaults.get(name.rsplit(".", 1)[-1].casefold())
        if not content:
            raise PresentationError("presentation part lacks a content type")
        content_types[name] = content
        if (
            name.endswith((".xml", ".rels"))
            or content.endswith("+xml")
            or content
            in {
                "application/xml",
                "text/xml",
            }
        ):
            parse(name)
    relationships, external = {}, []
    for name in sorted(parts):
        if not name.endswith(".rels"):
            continue
        owner = _owner(name)
        if owner and owner not in parts:
            raise PresentationError("presentation relationship owner is absent")
        root = parse(name)
        if root.tag != f"{{{PKG}}}Relationships":
            raise PresentationError("invalid presentation relationship namespace")
        rows = {}
        for rel in root:
            rid, kind, target = rel.get("Id"), rel.get("Type"), rel.get("Target")
            mode = rel.get("TargetMode", "Internal")
            if (
                rel.tag != f"{{{PKG}}}Relationship"
                or not rid
                or rid in rows
                or not kind
                or not target
            ):
                raise PresentationError("ambiguous presentation relationship")
            if mode not in {"Internal", "External"}:
                raise PresentationError("invalid presentation relationship mode")
            if mode == "External":
                try:
                    scheme = urlsplit(target).scheme.lower()
                except ValueError:
                    scheme = "invalid"
                row = {
                    "type": kind,
                    "external": True,
                    "target_sha256": hashlib.sha256(target.encode()).hexdigest(),
                    "scheme": scheme if scheme in {"https", "http", "file", "mailto"} else "other",
                }
                external.append({"part": owner, "relationship": rid, **row})
            else:
                resolved = _target(owner, target)
                if resolved not in parts:
                    raise PresentationError(
                        "presentation internal relationship target is absent",
                        code="missing-internal-target",
                    )
                row = {"type": kind, "external": False, "target": resolved}
            rows[rid] = row
        relationships[owner] = rows
    for owner, tree in trees.items():
        if owner.endswith(".rels"):
            continue
        for node in tree.iter():
            for key, value in node.attrib.items():
                if key.startswith("{" + R + "}") and value not in relationships.get(owner, {}):
                    raise PresentationError("presentation XML relationship reference is absent")
    office = [
        x for x in relationships.get("", {}).values() if x["type"].endswith("/officeDocument")
    ]
    if len(office) != 1 or office[0]["external"]:
        raise PresentationError("presentation has no unique internal officeDocument relationship")
    main = office[0]["target"]
    media = _MAIN_TYPES.get(content_types[main], "application/zip")
    if media != PPTX_MEDIA_TYPE:
        raise UnsupportedPresentation(media, "unsupported-presentation-family")
    root = parse(main)
    if root.tag == "{http://purl.oclc.org/ooxml/presentationml/main}presentation":
        raise UnsupportedPresentation(media, "strict-ooxml")
    if root.tag != f"{{{P}}}presentation":
        raise PresentationError("invalid presentation main-part namespace")
    if any("vbaproject" in value.casefold() for value in content_types.values()) or any(
        row["type"].casefold().endswith("/vbaproject")
        for rows in relationships.values()
        for row in rows.values()
    ):
        raise UnsupportedPresentation(media, "macro-bearing-package")
    # Bound the reader's recursive graph walk without depending on its silent skips.
    visited, graph_steps = set(), 0
    stack = [("", 0)]
    while stack:
        graph_steps += 1
        if graph_steps > 100000:
            raise PresentationLimitError("presentation relationship traversal limit exceeded")
        owner, depth = stack.pop()
        if owner in visited:
            continue
        if depth > 64:
            raise PresentationLimitError("presentation relationship depth limit exceeded")
        visited.add(owner)
        # Reverse only the stack insertion, preserving the reader's actual
        # relationship-order DFS and global visited semantics.
        for row in reversed(list(relationships.get(owner, {}).values())):
            if not row["external"]:
                stack.append((row["target"], depth + 1))
    slide_list = root.find(f"{{{P}}}sldIdLst")
    if slide_list is None or not 1 <= len(slide_list) <= 1000:
        raise PresentationLimitError("presentation slide count is outside the supported range")
    slides, ids, slide_parts, notes_parts = [], set(), set(), set()
    for element in slide_list:
        try:
            identifier = int(element.get("id", ""))
            rel = relationships[main][element.get(f"{{{R}}}id")]
        except (ValueError, KeyError) as exc:
            raise PresentationError("presentation slide identity is unresolved") from exc
        if (
            element.tag != f"{{{P}}}sldId"
            or not 256 <= identifier < 2147483648
            or identifier in ids
            or rel["external"]
            or rel["type"] != R + "/slide"
            or rel["target"] in slide_parts
        ):
            raise PresentationError(
                "presentation slide identity/order is ambiguous", code="ambiguous-slide-identity"
            )
        part = rel["target"]
        if (
            content_types[part]
            != "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
        ):
            raise PresentationError("presentation slide content type is inconsistent")
        if parse(part).tag != f"{{{P}}}sld":
            raise PresentationError("presentation slide part has the wrong namespace")
        notes = [
            row for row in relationships.get(part, {}).values() if row["type"] == R + "/notesSlide"
        ]
        if len(notes) > 1 or any(row["external"] for row in notes):
            raise PresentationError("presentation notes ownership is ambiguous")
        if notes:
            notes_part = notes[0]["target"]
            back_links = [
                row
                for row in relationships.get(notes_part, {}).values()
                if row["type"] == R + "/slide"
            ]
            if (
                notes_part in notes_parts
                or len(back_links) != 1
                or back_links[0]["external"]
                or back_links[0]["target"] != part
            ):
                raise PresentationError(
                    "presentation notes ownership is ambiguous", code="ambiguous-notes-owner"
                )
            notes_parts.add(notes_part)
            if (
                content_types[notes_part]
                != "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
                or parse(notes_part).tag != f"{{{P}}}notes"
            ):
                raise PresentationError("presentation notes part is inconsistent")
        ids.add(identifier)
        slide_parts.add(part)
        slides.append({"slide_id": identifier, "part": part})
    return {
        "parts": parts,
        "trees": trees,
        "types": content_types,
        "relationships": relationships,
        "external": external,
        "main": main,
        "slides": slides,
    }


def _extract(blob: bytes, include_notes: bool) -> dict:
    admitted = _admit(blob)
    from pptx import Presentation
    from pptx.enum.shapes import PP_PLACEHOLDER

    deck = Presentation(io.BytesIO(blob))
    # Presentation.slides renames parts to match ordinal order even on read.
    # Resolve original relationships directly to retain source part identity.
    native_ids = deck.part._element.sldIdLst
    if native_ids is None or len(native_ids) != len(admitted["slides"]):
        raise PresentationError("reader changed the admitted slide sequence")
    native_slides = [deck.part.related_slide(item.rId) for item in native_ids]
    assets = {
        name: {
            "part": name,
            "media_type": admitted["types"][name],
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "occurrences": [],
        }
        for name, data in admitted["parts"].items()
        if name not in admitted["trees"] and name != "[Content_Types].xml"
    }
    total_shapes, text_bytes = 0, 0
    slides = []
    deck_features = set()
    if any(
        row["type"].rsplit("/", 1)[-1].casefold()
        in {
            "comments",
            "commentauthors",
            "moderncomments",
            "threadedcomment",
        }
        for rows in admitted["relationships"].values()
        for row in rows.values()
    ):
        deck_features.add("comment-related-parts-not-extracted")

    def shape_text(shapes, features: set, *, notes: bool = False) -> str:
        nonlocal total_shapes
        lines = []
        for element in shapes._spTree:
            tag = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""
            if element.tag in _SHAPE_METADATA or not tag:
                continue
            total_shapes += 1
            if total_shapes > 20000:
                raise PresentationLimitError("presentation shape count limit exceeded")
            if element.tag not in _SHAPE_TAGS:
                features.add("unrendered-content:" + tag)
                continue  # unknown raw elements may not support the reader's shape factory
            shape = shapes._shape_factory(element)
            if (
                notes
                and shape.is_placeholder
                and shape.placeholder_format.type
                in {
                    PP_PLACEHOLDER.DATE,
                    PP_PLACEHOLDER.HEADER,
                    PP_PLACEHOLDER.FOOTER,
                    PP_PLACEHOLDER.SLIDE_NUMBER,
                    PP_PLACEHOLDER.SLIDE_IMAGE,
                }
            ):
                continue
            if tag == "grpSp":
                lines.append(shape_text(shape.shapes, features, notes=notes))
            elif shape.has_text_frame:
                lines.append(shape.text_frame.text.replace("\v", "\n"))
            elif shape.has_table:
                for row_number, row in enumerate(shape.table.rows, 1):
                    for col_number, cell in enumerate(row.cells, 1):
                        if cell.text:
                            lines.append(
                                f"[Table row {row_number}, cell {col_number}] " + cell.text
                            )
            else:
                # GraphicFrame.shape_type can be None (SmartArt), and generic
                # BaseShape.shape_type can raise (ink/unknown shapes). The
                # source tag remains available without invoking those getters.
                features.add("unrendered-shape:" + tag)
        result = "\n\n".join(x for x in lines if x.strip())
        return result

    for source, slide in zip(admitted["slides"], native_slides, strict=True):
        if (
            slide.slide_id != source["slide_id"]
            or str(slide.part.partname).lstrip("/") != source["part"]
        ):
            raise PresentationError("reader changed original slide identity")
        root = admitted["trees"][source["part"]]
        show = root.get("show", "1")
        if show not in {"0", "1", "false", "true"}:
            raise PresentationError("invalid hidden-slide state")
        features = set()
        # Unknown shape-tree children can be invisible to python-pptx's shape
        # iterator. Preserve that limitation explicitly rather than claiming an
        # empty extracted string accounts for their visible content.
        known_children = _SHAPE_TAGS | _SHAPE_METADATA | {f"{{{P}}}contentPart"}
        for tree in root.iter(f"{{{P}}}spTree", f"{{{P}}}grpSp"):
            if any(
                isinstance(child.tag, str) and child.tag not in known_children for child in tree
            ):
                features.add("unrendered-content:unknown-shape")
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            local = element.tag.rsplit("}", 1)[-1]
            if local == "graphicData":
                uri = element.get("uri", "")
                if uri != _DRAWING + "/table":
                    kind = {_DRAWING + "/chart": "chart", _DRAWING + "/diagram": "smartart"}.get(
                        uri, "graphic"
                    )
                    features.add("unrendered-content:" + kind)
            elif local in {
                "timing",
                "oleObj",
                "contentPart",
            }:
                features.add("unrendered-content:" + local)
            elif local == "transition":
                features.add("transition-not-rendered")
            elif local == "AlternateContent":
                features.add("alternate-content-not-interpreted")
        text = shape_text(slide.shapes, features)
        notes_present = slide.has_notes_slide
        notes = ""
        if notes_present and include_notes:
            notes = shape_text(slide.notes_slide.shapes, features, notes=True)
        text_bytes += len(text.encode()) + len(notes.encode())
        if text_bytes > MAX_OUTPUT:
            raise PresentationLimitError("presentation extracted text limit exceeded")
        # The inventory is independent of the reader, including repeated references.
        queue = deque([(source["part"], "slide")])
        visited = set()
        while queue:
            owner, scope = queue.popleft()
            if (owner, scope) in visited:
                continue
            visited.add((owner, scope))
            for rid, rel in admitted["relationships"].get(owner, {}).items():
                if rel["external"]:
                    features.add("external-resource-unvisited")
                    continue
                target = rel["target"]
                owner_type = admitted["types"].get(owner, "")
                if owner_type.endswith("slideMaster+xml") and rel["type"] == R + "/slideLayout":
                    continue  # sibling layouts are not occurrences on this slide
                next_scope = scope
                if rel["type"].endswith("/notesMaster"):
                    next_scope = "notes-master"
                elif rel["type"].endswith("/notesSlide"):
                    next_scope = "notes"
                elif rel["type"].endswith(("/slideLayout", "/slideMaster")) and scope not in {
                    "notes",
                    "notes-master",
                }:
                    next_scope = "inherited"
                # Notes link back to their slide; do not turn slide assets into notes assets.
                if rel["type"] == R + "/slide":
                    continue
                if target in assets:
                    locations = []
                    if owner in admitted["trees"]:
                        tree = admitted["trees"][owner].getroottree()
                        for node in admitted["trees"][owner].iter():
                            if any(
                                k.startswith("{" + R + "}") and v == rid
                                for k, v in node.attrib.items()
                            ):
                                locations.append(tree.getpath(node))
                    for locator in locations or ["relationship-only"]:
                        occurrence = {
                            "slide_id": source["slide_id"],
                            "scope": next_scope,
                            "source_part": owner,
                            "relationship": rid,
                            "locator": locator,
                        }
                        if occurrence not in assets[target]["occurrences"]:
                            assets[target]["occurrences"].append(occurrence)
                if target in admitted["trees"] and next_scope == "inherited":
                    if any(
                        node.tag == f"{{{A}}}t" and node.text
                        for node in admitted["trees"][target].iter()
                    ):
                        deck_features.add("master-layout-text-not-flattened")
                queue.append((target, next_scope))
        slides.append(
            {
                **source,
                "hidden": show in {"0", "false"},
                "text": text,
                "notes": notes,
                "notes_present": notes_present,
                "notes_included": include_notes,
                "features": sorted(features),
            }
        )
    custom_shows = []
    for show in admitted["trees"][admitted["main"]].findall(f"{{{P}}}custShowLst/{{{P}}}custShow"):
        paths = [
            admitted["relationships"][admitted["main"]][n.get(f"{{{R}}}id")]["target"]
            for n in show.findall(f"{{{P}}}sldLst/{{{P}}}sld")
        ]
        custom_shows.append(
            {
                "name": show.get("name", ""),
                "slide_ids": [
                    next(s["slide_id"] for s in slides if s["part"] == part) for part in paths
                ],
            }
        )
    return {
        "slides": slides,
        "assets": list(assets.values()),
        "external": admitted["external"],
        "custom_shows": custom_shows,
        "deck_features": sorted(deck_features),
    }


def presentation_mirror(path: Path, options, *, include_notes: bool = True):
    """Convert through the bounded private worker; never save or rewrite the deck."""
    from .mirror import Mirror, build_header, title_from_name
    from .presentation_worker import run_presentation

    if type(include_notes) is not bool:
        raise PresentationError("presentation notes selection must be boolean")
    result, digest, size = run_presentation(Path(path), include_notes)
    body, mapping = assemble_slides(
        options.title or title_from_name(path.name), result["slides"], digest
    )
    flags = {"presentation-native-only"}
    flags.update(result["deck_features"])
    flags.update(feature for slide in result["slides"] for feature in slide["features"])
    if not include_notes:
        flags.add("presentation-notes-excluded")
    if result["custom_shows"]:
        flags.add("presentation-custom-shows-not-canonical")
    header = build_header(
        path,
        method="pptx-native-extract",
        mirror_of=options.mirror_of,
        media_type=PPTX_MEDIA_TYPE,
        acquired_at=options.acquired_at,
        acquisition_method=options.acquisition_method,
        acquired_from=options.acquired_from,
        agent=options.agent,
        verify=(*options.verify, *flags),
        unit="slide",
        mirror_format=SLIDE_FORMAT,
        extensions=options.extensions,
        extra={
            "slide_count": len(result["slides"]),
            "slide_map": mapping,
            "presentation": {
                "notes_policy": "include" if include_notes else "exclude",
                "text_order": "drawing-order",
                "visual_fidelity": False,
                "reader": "python-pptx/1.0.2",
                "custom_shows": result["custom_shows"],
            },
            "presentation_assets": result["assets"],
            "presentation_external": result["external"],
        },
    )
    if header["content_hash"] != "sha256:" + digest or header["byte_size"] != size:
        raise PresentationError("presentation source changed during conversion")
    split_slides(header, body)
    return Mirror(header, body)

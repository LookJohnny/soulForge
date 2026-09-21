"""Agora's own RTC token builder, vendored unmodified.

Source: https://github.com/AgoraIO/Tools
        DynamicKey/AgoraDynamicKey/python3/src/{AccessToken2,RtcTokenBuilder2,Packer}.py
Copyright (c) Agora.io, Inc. — MIT licensed upstream.

Vendored rather than hand-written because a wrong RTC signature is rejected
silently: the channel join simply never succeeds and there is no readable error.
We lost a long debugging session to exactly that with Alibaba's ARTC.

Vendored rather than taken from PyPI because `agora-token-builder` there is a
community fork, pinned at 1.0.0, with no declared license — and it predates the
AccessToken2 ("007") format that Vidu's component edition needs.

The three files are byte-for-byte upstream so they can be diffed against a newer
release; only this __init__ is ours, and it exists so their relative imports
resolve as a package.
"""

from .RtcTokenBuilder2 import Role_Publisher, Role_Subscriber, RtcTokenBuilder

__all__ = ["RtcTokenBuilder", "Role_Publisher", "Role_Subscriber"]

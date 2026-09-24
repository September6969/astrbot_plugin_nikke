# SPDX-License-Identifier: GPL-3.0-or-later
"""CDK feature provider。"""

from __future__ import annotations

from ...features.cdk.service import CdkService
from ...integrations.blablalink.client import BlaBlaClient


def create_cdk_service(client: BlaBlaClient) -> CdkService:
    """用共享 API client 创建唯一 CDK service。"""
    return CdkService(client)

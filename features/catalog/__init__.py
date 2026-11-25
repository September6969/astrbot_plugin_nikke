# SPDX-License-Identifier: GPL-3.0-or-later
"""统一功能目录：为 QQ 帮助、公共大厅与个人指挥官工作台提供单一权威元数据。"""

from .registry import (
    CATEGORIES,
    FEATURES,
    CategorySpec,
    FeatureEntry,
    all_features,
    filter_features,
    get_feature,
    public_catalog_payload,
    workspace_catalog_payload,
)

__all__ = [
    "CATEGORIES",
    "FEATURES",
    "CategorySpec",
    "FeatureEntry",
    "all_features",
    "filter_features",
    "get_feature",
    "public_catalog_payload",
    "workspace_catalog_payload",
]

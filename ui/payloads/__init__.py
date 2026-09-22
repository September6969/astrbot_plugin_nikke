"""按页面边界组织 T2I payload builder。"""

from .profile import ProfileT2IPayloadBuilder
from .campaign import CampaignT2IPayloadBuilder

__all__ = ["CampaignT2IPayloadBuilder", "ProfileT2IPayloadBuilder"]

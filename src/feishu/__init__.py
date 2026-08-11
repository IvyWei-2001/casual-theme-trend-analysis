"""Read-only Feishu integration boundaries."""

from .client import FeishuClient
from .errors import (
    FeishuAPIError,
    FeishuAuthenticationError,
    FeishuConfigurationError,
    FeishuError,
    FeishuFieldIntegrityError,
    FeishuHTTPError,
    FeishuMalformedResponseError,
    FeishuPartialProvisioningError,
    FeishuRequestError,
    FeishuSchemaCompatibilityError,
    FeishuSchemaIntegrityError,
    FeishuSchemaValidationError,
    FeishuSchemaVerificationError,
    FeishuTimeoutError,
)
from .field_schema import (
    DESIRED_FEISHU_FIELDS,
    FeishuDesiredField,
    FeishuIncompatibleField,
    FeishuSchemaPlan,
    FeishuSchemaProvisionResult,
    desired_feishu_fields,
)
from .models import (
    FeishuAccessToken,
    FeishuBitableField,
    FeishuClientConfig,
    FeishuFieldInspectionResult,
)

__all__ = [
    "FeishuAccessToken",
    "FeishuAPIError",
    "FeishuAuthenticationError",
    "FeishuBitableField",
    "FeishuClient",
    "FeishuClientConfig",
    "FeishuConfigurationError",
    "FeishuError",
    "FeishuFieldInspectionResult",
    "FeishuFieldIntegrityError",
    "FeishuHTTPError",
    "FeishuMalformedResponseError",
    "FeishuDesiredField",
    "FeishuIncompatibleField",
    "FeishuPartialProvisioningError",
    "FeishuRequestError",
    "FeishuSchemaCompatibilityError",
    "FeishuSchemaIntegrityError",
    "FeishuSchemaPlan",
    "FeishuSchemaProvisionResult",
    "FeishuSchemaValidationError",
    "FeishuSchemaVerificationError",
    "FeishuTimeoutError",
    "DESIRED_FEISHU_FIELDS",
    "desired_feishu_fields",
]

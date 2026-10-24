"""AWS integration package for Movie Magic.
Provides interfaces and factory functions for DynamoDB and SNS.
In Phase 1, works in local/demo mode without requiring live AWS credentials.
"""
from .client_factory import get_boto3_client, is_aws_configured
from .dynamodb import DynamoDBService
from .sns import SNSService

__all__ = ["get_boto3_client", "is_aws_configured", "DynamoDBService", "SNSService"]

# infra

- `docker/`: shared Docker assets (base images, nginx config) for local and CI builds.
- `terraform/`: AWS infrastructure as code (VPC, ECS Fargate, RDS PostgreSQL,
  ElastiCache Redis, S3, KMS, Secrets Manager, CloudFront, WAF). Added in Phase 8.

No credentials or state files are committed.

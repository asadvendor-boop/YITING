variable "region" {
  description = "Alibaba Cloud region for the shared judging ECS VM."
  type        = string
  default     = "ap-southeast-1"
}

variable "name_prefix" {
  description = "Short name prefix for the ECS VM and network resources."
  type        = string
  default     = "yiting"
}

variable "ecs_instance_type" {
  description = "ECS size used for the production-oriented single-node judging deployment."
  type        = string
  default     = "ecs.c6.xlarge"
}

variable "system_disk_size_gb" {
  description = "System disk size in GB."
  type        = number
  default     = 80
}

variable "ssh_key_pair_name" {
  description = "Existing Alibaba Cloud ECS key-pair name used for SSH. Do not use password SSH."
  type        = string
}

variable "ssh_source_cidr" {
  description = "CIDR allowed to SSH to the VM. Use a narrow operator IP range, not 0.0.0.0/0."
  type        = string
}

variable "public_bandwidth_mbps" {
  description = "Maximum public outbound bandwidth for the ECS instance."
  type        = number
  default     = 10
}

variable "tags" {
  description = "Tags applied to supported Alibaba Cloud resources."
  type        = map(string)
  default = {
    Project           = "YITING"
    DeploymentProfile = "ecs-single-node"
    ManagedBy         = "Terraform-parity-proof"
  }
}

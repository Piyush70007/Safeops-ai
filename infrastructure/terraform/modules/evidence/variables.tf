variable "name" {
  type = string
}

variable "force_destroy" {
  type    = bool
  default = true
}

variable "object_lock" {
  type    = bool
  default = false
}

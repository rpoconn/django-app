from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Object-level permission: only the user who placed the order may see it.

    Note the view *also* filters the queryset by user, so a non-owner gets a
    404 rather than a 403. Both layers are deliberate: the queryset filter
    stops enumeration, the permission class protects detail routes that take
    an instance from somewhere else.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        return obj.user_id == request.user.id

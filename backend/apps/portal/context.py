def navigation(request):
    return {"tenant": getattr(request, "tenant", None)}

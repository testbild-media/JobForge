from django.contrib import admin

from .models import Article, ArticleGroup, Category, Location, Movement, SetComponent, Stock, Unit


class SetComponentInline(admin.TabularInline):
    model = SetComponent
    fk_name = "set_article"
    extra = 0


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["number", "name", "kind", "group", "rental_price", "sale_price", "active"]
    list_filter = ["kind", "group", "active"]
    search_fields = ["number", "name", "barcode"]
    inlines = [SetComponentInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["code", "article", "serial_number", "location", "condition", "current_job"]
    list_filter = ["condition"]
    search_fields = ["code", "serial_number", "article__name"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["path", "code", "kind", "active"]
    search_fields = ["name", "code"]


@admin.register(Movement)
class MovementAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "kind", "article", "unit", "quantity", "job", "user"]
    list_filter = ["kind"]


admin.site.register([Category, ArticleGroup, Stock])

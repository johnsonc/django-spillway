from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.settings import api_settings

from spillway import filters, forms, mixins, renderers, serializers


class BaseGeoView(mixins.QueryFormMixin):
    """Base view for models with geometry fields."""
    model_serializer_class = serializers.FeatureSerializer
    query_form_class = forms.GeometryQueryForm

    def wants_default_renderer(self):
        """Returns true when using a default renderer class."""
        return isinstance(self.request.accepted_renderer,
                          tuple(api_settings.DEFAULT_RENDERER_CLASSES))


class GeoListView(BaseGeoView, ListAPIView):
    """Generic list view providing vector geometry representations."""
    renderer_classes = tuple(ListAPIView.renderer_classes) + (
        renderers.GeoJSONRenderer, renderers.KMLRenderer, renderers.KMZRenderer)
    filter_backends = (filters.SpatialLookupFilter, filters.GeoQuerySetFilter)


class BaseRasterView(BaseGeoView):
    """Base view for raster models."""
    model_serializer_class = serializers.RasterModelSerializer
    query_form_class = forms.RasterQueryForm

    def get_serializer_context(self):
        context = super(BaseRasterView, self).get_serializer_context()
        context.update(params=self.clean_params())
        return context


class RasterDetailView(BaseRasterView, RetrieveAPIView):
    """View providing access to a Raster model instance."""
    renderer_classes = tuple(RetrieveAPIView.renderer_classes) + (
        renderers.HFARenderer,
        renderers.GeoTIFFRenderer
    )


class RasterListView(BaseRasterView, ListAPIView):
    """View providing access to a Raster model QuerySet."""
    filter_backends = (filters.SpatialLookupFilter,)
    renderer_classes = tuple(ListAPIView.renderer_classes) + (
        renderers.HFAZipRenderer,
        renderers.GeoTIFFZipRenderer,
    )

def getMetaData():
    return {}


def register(app):
    # imported lazily so the package can also be imported outside the slicer (tests, dev.py)
    from . import AIAssistant
    return {"extension": AIAssistant.AIAssistant()}

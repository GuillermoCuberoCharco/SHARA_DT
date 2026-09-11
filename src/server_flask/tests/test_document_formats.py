import io
import unittest
import zipfile

from document_formats import DocumentFormatError, validate_document_format


def _minimal_pptx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types><Override ContentType=\"application/vnd.openxmlformats-officedocument."
            "presentationml.presentation.main+xml\"/></Types>",
        )
        archive.writestr("_rels/.rels", "<Relationships />")
        archive.writestr("ppt/presentation.xml", "<p:presentation />")
    return output.getvalue()


class DocumentFormatValidationTests(unittest.TestCase):
    def test_accepts_pdf_with_standard_mime_type(self):
        extension = validate_document_format(
            "tema.pdf",
            "application/pdf",
            b"%PDF-1.7\ncontenido\n%%EOF",
        )
        self.assertEqual(extension, ".pdf")

    def test_accepts_uppercase_pptx_with_generic_mime_type(self):
        extension = validate_document_format(
            "TEMA.PPTX",
            "application/octet-stream",
            _minimal_pptx_bytes(),
        )
        self.assertEqual(extension, ".pptx")

    def test_rejects_legacy_ppt(self):
        with self.assertRaises(DocumentFormatError) as context:
            validate_document_format("tema.ppt", "application/vnd.ms-powerpoint", b"contenido")
        self.assertEqual(context.exception.status_code, 415)

    def test_rejects_pdf_with_spoofed_content(self):
        with self.assertRaises(DocumentFormatError):
            validate_document_format("tema.pdf", "application/pdf", b"esto no es un PDF")

    def test_rejects_pptx_without_office_structure(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("archivo.txt", "contenido")

        with self.assertRaises(DocumentFormatError):
            validate_document_format("tema.pptx", "application/zip", output.getvalue())

    def test_rejects_pptx_with_parent_path(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                "<Types><Override ContentType=\"application/vnd.openxmlformats-officedocument."
                "presentationml.presentation.main+xml\"/></Types>",
            )
            archive.writestr("_rels/.rels", "<Relationships />")
            archive.writestr("ppt/presentation.xml", "<p:presentation />")
            archive.writestr("../fuera.txt", "contenido")

        with self.assertRaises(DocumentFormatError):
            validate_document_format("tema.pptx", "application/zip", output.getvalue())

    def test_rejects_office_zip_without_presentation_content_type(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("_rels/.rels", "<Relationships />")
            archive.writestr("ppt/presentation.xml", "<p:presentation />")

        with self.assertRaises(DocumentFormatError):
            validate_document_format("tema.pptx", "application/zip", output.getvalue())

    def test_rejects_mismatched_mime_type(self):
        with self.assertRaises(DocumentFormatError) as context:
            validate_document_format("tema.pdf", "text/plain", b"%PDF-1.7\n%%EOF")
        self.assertEqual(context.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()

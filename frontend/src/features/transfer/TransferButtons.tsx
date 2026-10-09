import { Download, Loader2, Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { usePermission } from '@/lib/permissions'
import { downloadFile, importPath, type ImportKind } from '@/lib/transfer'

/** "Import" and "Export" for a list page. Export sends the list's current filters and search. */
export function TransferButtons({ kind, params }: { kind: ImportKind; params: Record<string, unknown> }) {
  const { t } = useTranslation()
  const canImport = usePermission('contacts.import')
  const canExport = usePermission('contacts.export')
  const [exporting, setExporting] = useState(false)

  const exportCsv = async () => {
    setExporting(true)
    try {
      await downloadFile(`/${kind}/export/`, params, `${kind}.csv`)
    } catch {
      toast.error(t('transfer.exportFailed'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      {canImport && (
        <Button variant="outline" nativeButton={false} render={<Link to={importPath(kind)} />}>
          <Upload className="size-4" />
          {t('transfer.import')}
        </Button>
      )}
      {canExport && (
        <Button variant="outline" onClick={() => void exportCsv()} disabled={exporting} title={t('transfer.exportHint')}>
          {exporting ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
          {t('transfer.export')}
        </Button>
      )}
    </>
  )
}

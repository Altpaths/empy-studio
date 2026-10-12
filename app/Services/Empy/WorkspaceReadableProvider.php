<?php

namespace App\Services\Empy;

/**
 * Optional capability for providers that can read assigned files from the
 * already-mounted workspace instead of receiving their contents inline.
 *
 * This is deliberately a separate interface so existing adapters and test
 * fakes keep the inline behavior until they explicitly opt in.
 */
interface WorkspaceReadableProvider
{
    public function supportsWorkspaceRead(): bool;
}
